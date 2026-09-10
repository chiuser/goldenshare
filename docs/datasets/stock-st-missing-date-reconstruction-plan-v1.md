# ST 股票列表历史缺日修复工具说明

更新：2026-09-10。低频工具已实现；2026-05-06 的 25 日补数预测与审计保留在附录，本轮未核验后续生产补数结果，不授权重跑。

## 1. 用途与依赖

用于源站 `stock_st` 无法补回的**显式历史整日缺失**：用库内辅助证据重建当天 ST 成员。不是日常同步替代、开放区间生成器或部分缺行修复器。

- 正常维护仍由 [stock_st 数据集](/Users/congming/github/goldenshare/docs/datasets/stock-st-dataset-development.md)承担。
- 目标为 `raw_tushare.stock_st` 与 `core_serving.equity_stock_st` 两张现存物理表，主键均为 `(ts_code,trade_date,type)`。
- 读取 Serving 相邻快照、`raw_tushare.namechange`、`raw_tushare.st`。namechange/st 已有代码接入，但工具不会自动准备其数据，也不联网回退；表不存在或事实不足应先解决前提。
- 源语义见 [namechange 0100](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0100_股票曾用名.md)、[st 0423](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0423_ST风险警示板股票.md)。不从本说明推导新增 source 参数或临时接入接口。

实现位于 [修复包](/Users/congming/github/goldenshare/src/foundation/services/migration/stock_st_missing_date_repair)，不改变 stock_st Definition/date model，不新增长期 Ops/TaskRun 入口，不修改日常数据写入路线。

## 2. CLI 与模式

现有 [CLI](/Users/congming/github/goldenshare/src/cli.py)及 [handler](/Users/congming/github/goldenshare/src/cli_parts/stock_st_missing_date_repair_handlers.py)：

```text
goldenshare repair-stock-st-missing-dates
  --date YYYY-MM-DD                  # 可重复
  --date-file <日期文件>             # 一行一日期，可与 --date 合并
  --output-dir <报告目录>            # 可选
  --apply                           # 默认不传：只预览
  --fail-on-review-items             # 默认 false
```

日期合并、去重、排序后必须非空；日期文件支持忽略空行和注释。这里的占位符不是本轮执行指令。

| 模式 | 实际行为 |
| --- | --- |
| 不传 --apply | 读当前事实并生成三份 CSV，不写数据库 |
| --apply，默认 fail_on_review_items=false | **重新读取当前事实并重算全部预览**，跳过整个有审查项/冲突的日期，只写其他合格日期 |
| --apply --fail-on-review-items | 同样先重算并输出 CSV；任何日期不合格则整次拒绝 apply |

**apply 不读取此前批准的 CSV，也没有 plan hash 或内容冻结。** 因此不是“批准旧报告后照单落库”。人工操作建议显式加 `--fail-on-review-items`，并在事实稳定的维护窗口核验本次产物；这只是操作建议，不改默认值。如果业务要求严格按冻结的审批产物执行，当前工具不满足，需要单独设计和批准，不能假装已有该能力。

默认目录为相对当前工作目录的 `reports/stock_st_missing_date_repair/YYYYMMDD_HHMMSS`。三份产物：

- `stock_st_missing_date_preview_summary.csv`：逐日相邻日期/数量、候选数、有效名称记录数、未解数、非 ST 排除数、重建/验证/审查数及 apply_eligible。
- `stock_st_missing_date_preview_rows.csv`：纳入候选、输出名称、name_source、validation_status、前后名称及所选 namechange/同日事件证据。
- `stock_st_missing_date_manual_review.csv`：需要人工判断的代码、review_code/message 和证据；正常非 ST 排除不等于人工审查项。

## 3. 实际判定顺序

[候选查询](/Users/congming/github/goldenshare/src/foundation/services/migration/stock_st_missing_date_repair/candidate_loader.py)与[证据判定](/Users/congming/github/goldenshare/src/foundation/services/migration/stock_st_missing_date_repair/evidence_resolver.py)是当前事实源：

1. 对每个目标日 D，从 Serving 找严格早于/晚于 D 的最近快照。任一不存在直接失败；不把尚未提交的其他修复日当相邻快照。
2. 候选代码 = 前快照代码 ∪ 后快照代码 ∪ Raw st 中 `imp_date=D` 的代码。不是扫描全历史事件状态机，也不是只复制前一天。
3. 只查候选在 D 有效的 namechange：`start_date<=D` 且 `coalesce(end_date,9999-12-31)>=D`。按代码、start_date DESC、ann_date DESC、end_date DESC、id DESC 排序，三个日期排序显式 NULLS LAST；每代码取第一条。
4. 无有效 namechange 进入 `missing_namechange_interval` 审查；不能靠最近 ST 事件或相邻名称兜底成员身份。重叠区间按既定排序取一条，没有额外的“重叠歧义自动拒绝”门禁。
5. 所选名称经首尾去空白、循环去 XR/XD/DR 前缀、再去一次 N 前缀后，检查 S*ST/SST/*ST/ST 前缀；用于身份判定，不把归一化字符串写回输出名。
6. 所选名称非 ST：通常排除。只有同日事件的非空名称中存在 ST-like 名称才进入冲突审查，并非“有任何同日事件就冲突”。
7. 所选名称是 ST：若前后快照名称相同且等于所选名称，name_source=stable_snapshot；否则使用所选 namechange 名称。没有“读取最近历史 ST 事件给名称”的正常兜底链。
8. 同日事件有非空名称但全部非 ST-like，则进入审查；否则按有/无同日事件标记 ok。缺同日事件本身不阻断，`st_type` 只作证据记录，不驱动完整状态机。

辅助数据不完整仍可能限制候选发现与判定，不能由“没有审查项”证明全市场事实完整。工具保留这些低频人工使用边界，不自动扩大推断范围。

## 4. 写入、事务与溯源

[service](/Users/congming/github/goldenshare/src/foundation/services/migration/stock_st_missing_date_repair/service.py)在写入前检查**全部合格日期**的 Raw 和 Serving 均为零行；任一目标日任一表已有数据就拒绝整次写入。仅支持整日空桶，不覆盖、不 upsert、不删除原数据。

所有合格日期的 Raw/Serving 行通过同一 session 的 add_all 后**一次 commit**，不是逐日提交或逐文件 checkpoint。预检是查询，不是并发互斥；人工窗口必须协调其他写入，不能宣称已有排它锁。成功后重跑 apply 会因桶非空被拒绝，不能把 insert-only 称为幂等 upsert。

输出固定 `type=ST/type_name=风险警示板`。Raw 的 `api_name=stock_st_repair`，由 [writer](/Users/congming/github/goldenshare/src/foundation/services/migration/stock_st_missing_date_repair/writer.py)构造 JSON 溯源，不伪装源接口原始响应：

| payload 键 | 用途 |
| --- | --- |
| reconstruction / source_kind | true / db_namechange_primary |
| missing_date / prev_trade_date / next_trade_date | 重建日及相邻快照日期 |
| name_source / validation_status | 输出名称来源和验证结论 |
| selected_namechange | 所选名称、start/end/ann_date、change_reason |
| same_day_st_events | 事件列表；name、pub_date、imp_date、st_type、st_reason |
| evidence_sources | namechange_table=raw_tushare.namechange，st_table=raw_tushare.st |

不再使用旧文档里并不存在的 `namechange_interval/st_event_imp_date_hit` payload 键。

返回 `applied=True` 仅表示请求了 apply，不代表所有输入日期均写入。必须一起检查 applied_date_count、applied_row_count、skipped_review_dates 与当前 CSV。工具不自动跑日期完整性审计；获准写入后仍需独立读回两表、核对日期/行数/名称/证据及审计状态，不把 CSV 文件存在当成落库成功。

## 5. 回归与后续授权

现有[服务测试](/Users/congming/github/goldenshare/tests/test_stock_st_missing_date_repair_service.py)和 [CLI 测试](/Users/congming/github/goldenshare/tests/test_cli_repair_stock_st_missing_dates.py)覆盖主要流程；维护时重点检查相邻快照、ST 前缀、重叠排序、同日名称冲突、整日跳过/整次拒绝、双表空桶与一次提交。

本轮不运行 preview/apply，不改变候选算法、默认开关、事务或数据表。冻结审批产物、并发保护、分日 checkpoint、部分缺行修复均不是当前已实现能力；若确需新增，单独评审，不借文档治理开发。

## 6. 2026-05-06 历史审计附录

当时远端 Serving 范围为 2016-08-09 至 2026-04-30，type/type_name 只有 ST/风险警示板；识别 25 个整日缺失，含 2020-08-03～04 连续两日。源 stock_st 无法取得这些快照是当时已确认前提，不代表今天仍缺，不能复制清单再次 apply：

```text
2016-08-10
2016-08-19
2016-09-22
2016-10-10
2016-12-05
2017-01-17
2017-06-23
2019-04-01
2019-10-24
2019-11-04
2019-11-28
2020-01-02
2020-02-20
2020-02-25
2020-03-16
2020-04-23
2020-06-18
2020-07-08
2020-07-20
2020-08-03
2020-08-04
2020-08-24
2020-11-20
2021-01-29
2021-03-16
```

相邻快照不是稳定不变：2016-08-10 为 72→72，2019-04-01 为 91→89，2020-01-02 为 138→137，2021-03-16 为 215→214，因此不可简单前向填充。

用户补齐 namechange 历史后，当时 342 个候选代码、25 日均可选到有效记录，未解决候选为 0，预计 3,613 行；21 日稳定、4 日需排除边界成员：

| 日期 | 当时排除代码 |
| --- | --- |
| 2020-04-23 | 600225.SH |
| 2020-06-18 | 300028.SZ |
| 2020-08-24 | 600365.SH、601777.SH |
| 2021-03-16 | 600255.SH |

仅 7 个缺失日有同日 st 事件，再次说明其是辅助证据。早期阻塞代码 600793.SH 的名称历史已补齐：*ST宜纸（2008-02-01～2009-08-18）、ST宜纸（2009-08-19～2016-11-20）、宜宾纸业（2016-11-21 起）。这些是当时解阻证据，3,613 是预估而非本轮确认的生产写入量。
