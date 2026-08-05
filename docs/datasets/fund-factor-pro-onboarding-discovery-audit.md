# 基金技术面因子（专业版，`fund_factor_pro`）接入发现审计

状态：发现审计完成，**未进入 LLD、未建表、未写入远程数据**
首次审计：2026-08-03；复审：2026-08-05
截图菜单：基金技术面因子（专业版）
源文档：[场内基金技术因子（专业版）](../sources/tushare/公募基金/0359_场内基金技术因子(专业版).md)

## 结论

`fund_factor_pro` 是场内基金每日技术指标接口，不是全部公募基金净值因子。实测单日全市场 2,021 个唯一 `ts_code`，低于文档 8,000 行上限；`510300.SH` 全历史为 3,448 行（2012-05-28..2026-08-04），按 `trade_date` 和短区间均正常。接口无参数实际报“`ts_code,trade_date` 至少一个”，与本地文档“参数均可选”不一致。

它具备按交易日接入的候选基础，但字段数 90、历史体量大，且不能复用现有 ETF 活跃池：该池仅允许 `fund_daily`、`etf_rt_daily`、`etf_sh_cons` 三个 resource，设计初始规模为 1,395，不是本接口 2,021 代码的完整范围。

## 源端事实与实测

| 项目 | 已核验事实 | 接入含义 |
| --- | --- | --- |
| 无参数 | 参数校验失败，需 `ts_code` 或 `trade_date` | 不是 snapshot 接口。 |
| 单日全市场 | `trade_date=20260617` 为 2,021 行、2,021 个唯一代码 | 一个交易日全市场 unit 是候选，须做峰值日验证。 |
| 历史样本 | 全市场单日：2015-06-17 为 205、2018-06-15 为 344、2022-06-17 为 1,016、2024-06-17 为 1,322、2026-06-17 为 2,021 行 | 历史基金数递增，不能直接拿当前 2,021 只当作历史实际行数。 |
| 单代码历史 | `510300.SH` 3,448 行，2012-05-28..2026-08-04 | 对象历史可取，且给出 3,448 个候选交易日；不能代替全市场按日完整性证据。 |
| 点 / 短区间 | 单日 1 行、两日 2 行，显式 90 字段均返回 | `trade_date` point/range 可候选。 |
| 分页 | 单日 2,021/2,076 行低于文档 8,000 单页上限；当前无需分页，但 Definition 仍应保留峰值门禁，不得凭此断言永不触顶。 |
| 日期双字段 | `trade_date=YYYYMMDD` 与 `trade_date_doris=YYYY-MM-DD` 同时返回 | 两者均应显式请求，并在 M0 做一致性校验。 |
| 全字段负载 | 2026-06-17 显式请求 90 字段，2,021 行、90 列全部返回；响应共约 3.96MB，单行 JSON 平均约 1,767 字符 | 单日 unit 的网络和内存量可控；历史流量和 HDD 容量必须按宽表测算。 |

候选 `source_fields`（90 个，须每次请求完整传入）：

```text
ts_code, trade_date, trade_date_doris, open, high, low, close, pre_close,
change, pct_change, vol, amount, asi_bfq, asit_bfq, atr_bfq, bbi_bfq,
bias1_bfq, bias2_bfq, bias3_bfq, boll_lower_bfq, boll_mid_bfq,
boll_upper_bfq, brar_ar_bfq, brar_br_bfq, cci_bfq, cr_bfq, dfma_dif_bfq,
dfma_difma_bfq, dmi_adx_bfq, dmi_adxr_bfq, dmi_mdi_bfq, dmi_pdi_bfq,
downdays, updays, dpo_bfq, madpo_bfq, ema_bfq_10, ema_bfq_20,
ema_bfq_250, ema_bfq_30, ema_bfq_5, ema_bfq_60, ema_bfq_90, emv_bfq,
maemv_bfq, expma_12_bfq, expma_50_bfq, kdj_bfq, kdj_d_bfq, kdj_k_bfq,
ktn_down_bfq, ktn_mid_bfq, ktn_upper_bfq, lowdays, topdays, ma_bfq_10,
ma_bfq_20, ma_bfq_250, ma_bfq_30, ma_bfq_5, ma_bfq_60, ma_bfq_90,
macd_bfq, macd_dea_bfq, macd_dif_bfq, mass_bfq, ma_mass_bfq, mfi_bfq,
mtm_bfq, mtmma_bfq, obv_bfq, psy_bfq, psyma_bfq, roc_bfq, maroc_bfq,
rsi_bfq_12, rsi_bfq_24, rsi_bfq_6, taq_down_bfq, taq_mid_bfq,
taq_up_bfq, trix_bfq, trma_bfq, vr_bfq, wr_bfq, wr1_bfq, xsii_td1_bfq,
xsii_td2_bfq, xsii_td3_bfq, xsii_td4_bfq
```

候选身份键为 `(ts_code, trade_date)`；90 个数值字段应允许源端 warm-up null，只有身份与交易日期可先设为必填。

## 建议的接入轮廓（非 LLD）

| 维度 | 当前建议 |
| --- | --- |
| 时间 / unit | 交易日 point/range；range 由 resolver 按开市日展开，一个全市场交易日一个 unit。 |
| 完整性 | 先只做 date-bucket，不做“每基金每天”矩阵；是否所有场内基金都应有因子尚未证明。 |
| 对象范围 | 使用源端当日全市场，不复用 `ops.etf_series_active`；若要限定池，必须新建独立、公募基金口径的资源和治理方案。 |
| 存储 | 90 列 × 全历史是九项中空间最大者；使用 direct-serving 的当前表和观察版本表，不保存会重复 90 字段的 `raw_payload`；所有表、叶分区和索引固定 HDD，禁止 SSD。 |
| 自动化 | 支持手动和普通定时自动任务；数据源为社区自产，本期不接 probe。 |

## LLD 前仍需验证或决定

1. **历史容量已量化，作为上线门禁而非精确行数承诺**：取 3,448 个历史交易日与当前峰值 2,021 行相乘，得到保守上界 6,968,408 行。生产同构 90 列 `raw_tushare.idx_factor_pro` 的 catalog 统计为 1,309,609 行、heap 1,060,675,584 B、索引 67,846,144 B、总计 1,128,841,216 B，即约 862 B/行；据此初始当前事实约 5.6 GiB。建议为观察版本预留 50% 增量、按约 8.4 GiB 规划；这项预留不是源端已发生修订量。
2. **磁盘/WAL 门禁已通过但需运行时复核**：2026-08-05 只读审计显示 `gs_raw_cold_hdd` 所在 `/data/disk` 可用 346,520,969,216 B（约 322.7 GiB），表空间已占约 50.8 GiB；建议初始接入时 HDD 至少预留 15 GiB。物理业务表和索引均在 HDD；PostgreSQL WAL 仍会临时落在默认盘，不能由表 tablespace 改变。当前根盘可用约 22.3 GiB，建议历史回补前至少 20 GiB、运行中低于 15 GiB 停止，且不得与其他大回补并发。
3. **请求量/配额门禁**：按一交易日一个 unit，当前历史样本为 3,448 次请求；当前均未触发 8,000 行分页上限。源文档给出 5,000 积分 30 次/分、8,000 积分 500 次/分；在未核验生产积分档位前，建议实施基线按 30 次/分限速，理论下界约 115 分钟（500 次/分才约 7 分钟）。以当前高密度日的 1,767 字符/行估算，历史响应流量上界约 11.5 GiB。必须保留 `offset_limit`，并在任何单日满 8,000 行时继续请求 short page，不能把“当前未触顶”编码为永不分页。
4. 发布时点、修订检查和连续日期 audit 规则，需以多日真实样本确认；若采用连续 freshness，必须另加“禁止 probe”的自动化能力约束。

## 已冻结的日度事实与修订原则（非 LLD）

1. 日度因子逻辑身份为 `(ts_code, trade_date)`；`trade_date_doris` 是同一日期的源字段，必须保存并在归一化时校验与 `trade_date` 一致，不能另作第二个日期主键。
2. 全部 90 个源字段原样保存；同一逻辑身份内容变化时保留观察版本、内容散列和首次/最后一次观察时间。指标 warm-up 空值是源事实，不得以 0 补齐。
3. 对象范围已定为源端全市场场内基金（实测单日 2,021 只），不复用 ETF 活跃池；所有事实表、叶分区与索引放 HDD。
