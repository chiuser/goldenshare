# DG 人工数据例外记录

本文件记录管理员明确批准的单次数据修正，不由运行代码读取，不形成自动补值规则。

## ETF-512390-20260910-11

- 批准日期：2026-09-12。
- 批准内容：管理员要求记录例外后手动补数，本次不修改原 LLD 或生产代码。
- 对象：512390.SH，平安MSCI中国A股低波动ETF。
- 背景：基金进入清算、不再恢复交易；Tushare ETF Basic 当前仍为 L，因子接口缺少目标日记录。
- 已核实来源：正式 Raw/Silver 的 2026-09-08、2026-09-09 因子均为 1.3094。
- 人工假设：仅对 2026-09-10、2026-09-11 沿用 2026-09-09 的 adj_factor=1.3094；不是源站返回或独立验证的当日值。
- discount_rate：填 NULL，不沿用 2026-09-09 的 -0.5079。贴水率未取得当日证据，现行 schema 允许 NULL。
- 范围：Raw `raw/tushare/fund_adj/trade_date=<date>/part-000.parquet` 与 Silver `silver/quote/etf_adj_factor/trade_date=<date>/part-000.parquet`，根为 `/Volumes/datasource/data_lake`。
- 既有文件只追加该代码的一行，其他行必须双向 EXCEPT ALL 为零；缺失 Silver 由既有 job 生成。
- 写入：候选只在 `/Volumes/datasource/data_lake_staging`，校验后逐文件 os.replace；保留文件指纹和进度报告至 `/private/tmp`。不删除历史事件，不备份 Lake，不修改 Basic 状态。
- 状态验收：刷新当日 Basic 后按 9月10日、11日顺序执行现有 Silver job 和 checks；正式 run tags 引用本例外编号。
- 后续注意：Raw 这两行是人工例外，不能再称为纯源站镜像。普通 Raw 重拉若与源站冲突，会拒绝覆盖；必须依据本记录另行处理，不能扩大自动覆盖权限。
- 范围截止：不处理 9月12日及之后，不认定正式退市日，不将停牌自动解释为因子不变。
- 执行状态：2026-09-12 已完成。三个既有文件的候选全部校验后逐文件提升，非目标代码行的双向 EXCEPT ALL 均为零。临时脚本首次 SQL 解析失败发生在写候选前，未改正式文件；修正临时脚本后执行成功。
- 最终行数：9月10日 Raw 2149、Silver 1650；9月11日 Raw 2150、Silver 1650。两日该代码均为 adj_factor=1.3094、discount_rate=NULL。
- Basic 刷新：Raw run `60621756-3d52-4705-8ed5-b713543a1fc5`、Silver run `a95e9173-7b61-44cc-9b1e-64e4a04f71ee`，均成功；内容仍复用既有快照，没有改动 L 状态。
- Silver 9月10日：run `a700b4b9-7c48-4bac-85b6-c6325f4c29c1`，SUCCESS，六个检查全部通过。
- Silver 9月11日：run `19308bc4-169e-450e-985b-f228515a7381`，SUCCESS，六个检查全部通过。
- 物理写入与指纹报告：`/private/tmp/etf_512390_exception_20260912T070807.json`。
- 最终文件与状态审计：`/private/tmp/etf_512390_exception_final_20260912.json`。
- 没有重写旧 Raw materialization 的行数/hash metadata，没有补录 Raw event；旧 Raw metadata 仍描述原始源请求，修正后的物理事实以本记录和报告为准。
