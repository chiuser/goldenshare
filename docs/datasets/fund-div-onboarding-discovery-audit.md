# 基金分红（`fund_div`）接入发现审计

状态：发现审计完成，**未进入 LLD、未建表、未写入远程数据**
首次审计：2026-08-03；复审：2026-08-05
截图菜单：基金分红
源文档：[公募基金分红](../sources/tushare/公募基金/0120_公募基金分红.md)

## 结论

`fund_div` 是事件型分红接口。实际要求 `ts_code`、`ann_date`、`ex_date`、`pay_date` 至少一个；没有无参数全量、没有区间参数。因此历史全市场只能按某一个事件日期逐日扇出，或按基金代码分别查取，不能设计成一次区间请求。分页实测可用：`ann_date=20260617`、16 字段、`limit=50` 的三页为 50/50/22、无重叠。

经 2026-08-05 复核，先前“冲突版本”的结论过短：若只用 `ts_code + 公告日 + 实施公告日 + 除息日`，122 行确有 59 个重复组；但把源端全部可用事件日期联合起来后，122 行是 **122 个唯一记录、0 个重复组**。区别记录至少由 `net_ex_date` 区分，不是可以静默覆盖的同一行。

## 源端事实与实测

| 项目 | 已核验事实 | 接入含义 |
| --- | --- | --- |
| 无参数 | 参数校验失败 | 不能做 snapshot refresh。 |
| 日期点 | `ann_date=20260617` 返回 122 行 | 可按公告日取增量。 |
| 单基金 | `000001.OF` 显式全字段返回 29 行 | 可做代码范围历史查询，完整性仍未证明。 |
| 区间 | 接口不存在 `start_date/end_date` | range 必须由 planner 扇出自然日，不是源端区间。 |
| 分页 | `limit=50, offset=0/50/100` 为 50/50/22，日期签名无重叠 | 使用 `offset_limit`；仍须量化公告日峰值。 |
| 事件身份复核 | `ts_code, ann_date, imp_anndate, base_date, record_date, ex_date, pay_date, earpay_date, net_ex_date, account_date, base_year` 联合后为 122 个唯一记录 | 原先候选键遗漏 `net_ex_date` 等事件日期；不得再按短键覆盖。 |

候选 `source_fields`：

```text
ts_code, ann_date, imp_anndate, base_date, div_proc, record_date, ex_date,
pay_date, earpay_date, net_ex_date, div_cash, base_unit, ear_distr,
ear_amount, account_date, base_year
```

## 建议的接入轮廓（非 LLD）

| 维度 | 当前建议 |
| --- | --- |
| 时间语义 | `natural_day` 事件型；point=`ann_date`，range 仅表示自然日 fan-out。 |
| freshness / audit | `not_applicable`；没有分红的自然日不是缺数。 |
| unit / 事务 | 一个公告日完整分页结果一个 unit；源端不支持区间，仍要先测峰值后设 `max_units_per_execution`。 |
| 身份 | 以全量日期签名作为候选源记录身份；对数据库 nullable 复合键，LLD 使用带显式 null 标记的稳定身份散列，并在同散列内容不一致时失败，不允许 DAO 最后一行覆盖。 |
| 存储 | 所有 16 个字段保真保存；物理表、所有叶分区与索引固定 HDD。 |
| Ops / 自动化 | 新“公募基金”分组；支持手动 + 普通定时自动任务，不接 probe。 |

## 必须拍板

1. 先前短日期键导致的“冲突版本”已排除；无需进行信息更完整优先级合并。
2. LLD 需把全量日期签名的 null 标记、内容冲突失败策略和实体主键固化，禁止缩回短键。
3. 历史回补范围、按公告日自然日扇出上限和限流策略；接口没有源端范围查询。
4. `ts_code` 是否作为运营精确补录筛选仍需按事件时间语义设计，但不影响全字段保真保存。

## 已冻结的事件身份与修订原则（非 LLD）

1. 分红是事件事实，不按“最新一行覆盖历史”处理。逻辑事件身份为 `ts_code` 加全部可用事件日期：`ann_date, imp_anndate, base_date, record_date, ex_date, pay_date, earpay_date, net_ex_date, account_date, base_year`；数据库以对这些字段及显式空值标记计算的稳定事件散列承载。
2. 同一事件散列但其余源字段内容不同，必须拒绝并报告冲突，不能用 DAO 的最后一行覆盖。若源端后来确认存在可辨识修订语义，才在 LLD 定义观察版本；当前先完整保留 16 个源字段和冲突证据。
