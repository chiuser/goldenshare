# 月线补齐执行后审计

2026-10-02 22:14–22:16（Asia/Shanghai）Prod 只读复查：本批 32 个任务全部成功，12 只目标股票原来的 666 个 Raw 月线缺失键已清零。Raw 与 Serving 的未复权、复权四层覆盖均完整，业务字段一致。

## 执行结果

| 项目 | 结果 |
| --- | ---: |
| 任务 | 32 / 32 success |
| 全部执行节点 | 32 / 32 success |
| 完成单位 | 266 / 266 |
| 失败单位 | 0 |
| 任务报告拉取行数 | 881,721 |
| 任务报告保存行数 | 881,721 |
| 拒绝行数 | 0 |
| 未结束节点或终态缺失结束时间 | 0 |

任务 ID 为 14234、14236–14266。执行从 21:37:08 开始，最后一项于 22:05:32 成功结束。881,721 是本批全市场任务报告的累计保存计数，包含已有记录更新，不能解读为新增行数或补齐缺口数。

## 物理数据复查

股票：002235.SZ、002769.SZ、002812.SZ、300165.SZ、300710.SZ、600222.SH、601059.SH、601198.SH、601995.SH、688051.SH、688536.SH、688766.SH。

范围为 2010-01-01 至 2026-09-30。以 raw_tushare.daily 中该股票该月出现交易记录为预期条件，生成去重的股票月份键。采用此前审计的自然月末锚点；2020 年 2 月遵从管理员决定，锚点为 2020-02-28，2020-02-29 不计作有效覆盖。

| 层 | 预期股票月份键 | 实际匹配 | 缺失 |
| --- | ---: | ---: | ---: |
| Raw 未复权 | 1,407 | 1,407 | 0 |
| Raw 复权 | 1,407 | 1,407 | 0 |
| Serving 未复权 | 1,407 | 1,407 | 0 |
| Serving 复权 | 1,407 | 1,407 | 0 |

补齐前这 12 只股票的 Raw 未复权和复权各缺失 333 个键；当前全部覆盖。本批任务不包含 2020 年 2 月，该月此前已存在的 28 日数据仍能满足这 12 只股票的覆盖。没有删除或变更 Prod 中的 29 日历史记录。

## 字段一致性

在相同代码、日期范围内排除 2020-02-29，按 ts_code、trade_date、freq 对 Raw 与 Serving 进行完整外连接。未复权和复权分别核对 1,407 对记录：双方独有键均为 0，业务字段差异均为 0。

字段包括 end_date、open/high/low/close、pre_close、vol、amount、change、pct_chg；复权额外核对前复权和后复权各四个价格字段。按当前 row_transforms.py 中的映射，以 Raw.change 对照 Serving.change_amount；未比较抓取时间、更新时间和 raw_payload 等技术字段。

Raw 两个版本均没有 OHLC 空值，也没有 high 低于 open/close/low 或 low 高于 open/close/high 的范围异常。本次没有重新向 Tushare 发出请求，不构成源端最新价格正确性的再次验收。

## 查询与文件

通过既有 bash scripts/psql-remote.sh 访问 Prod PostgreSQL。所有查询使用 BEGIN READ ONLY，并在结束时 ROLLBACK；声明白名单和字段投影，statement_timeout 为 15–30 秒。任务查询限定本次 submission_batch_key；覆盖和字段查询限定 12 个代码、month 频率及上述日期范围。没有写入数据库、提交新任务、修改代码或配置。

白名单：ops.task_run、ops.task_run_node、raw_tushare.daily、raw_tushare.stk_period_bar、raw_tushare.stk_period_bar_adj、core_serving.stk_period_bar、core_serving.stk_period_bar_adj。Ops 投影为任务 ID、输入、状态、计数、时间及节点状态；daily 仅投影代码和交易日期；行情表仅投影键和上述业务字段。结果按聚合导出，无全表数据导出：任务 32 行、节点 32 组、覆盖 48 组、字段对账 2 组。

新增文件：

- stock_month_backfill_completed_task_status_20261002.csv：32 个任务终态及计数。
- stock_month_backfill_completed_node_status_20261002.csv：全部节点状态核验。
- stock_month_backfill_completed_coverage_20261002.csv：逐股票、逐层的覆盖统计。
- stock_month_backfill_completed_reconciliation_20261002.csv：字段对账及 OHLC 检查。
- stock_month_backfill_completed_summary_20261002.json：机器可读汇总。
- 本审计报告。

原来的提交记录和全历史缺口报告保留为历史快照。本次未影响架构边界或依赖矩阵，未提交或推送 Git。

## 结论与边界

本批目标缺口补齐通过，可以作为后续 DG 月线接入评估的已验收输入。当前无需为这 12 只股票再次提交相同补齐任务。

本次没有重新审计全市场的全部历史键，也没有逐行对账 881,721 条全市场保存记录；退市、旧代码、北交所映射和 2010 年之前的范围仍不能由本结果认定完整。后续接入 DG 时继续使用 2020-02-28 的决定，并单独解决源接口输入及月末执行计划的日期契约。
