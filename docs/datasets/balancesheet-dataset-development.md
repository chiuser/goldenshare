# A 股资产负债表（balancesheet）维护说明

更新时间：2026-09-10。已实现；2026-08-30 已完成下文所列初始范围的 Prod 验收，原开发需求关闭。原 LLD 有效内容已合入本页及共用规则；本次不重新认证当前生产数据、源接口或部署状态。

## 1. 当前链路与共用规则

`balancesheet.maintain → 公告自然日×report_type units → balancesheet_vip 分页 → Raw 规范化/upsert → Serving 普通 view`。

本表完整沿用[财务三表共用规则](/Users/congming/github/goldenshare/docs/datasets/income-dataset-development.md#financial-statement-shared-rules)：公告日而非报告期输入、默认真实 1..12、多选全选交互、七字段身份、end_type 规范化、指纹与修订、HDD/视图选择、事务、Ops 和调度。这里不再复制另一套共享合同。

| 本表事实 | 当前值 |
| --- | --- |
| Definition | [low_frequency.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/low_frequency.py) 中 balancesheet，domain=low_frequency |
| API / source_doc_id | balancesheet_vip / tushare.balancesheet |
| 源字段 / 数值字段 | 158 / 150，显式字段由 [balancesheet_contracts.py](/Users/congming/github/goldenshare/src/foundation/datasets/balancesheet_contracts.py) 固定，不依赖默认响应 |
| Raw / DAO | raw_tushare.balancesheet / raw_balancesheet，GenericDAO |
| ORM | [RawBalancesheet](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_balancesheet.py) |
| Serving | core_serving.equity_balancesheet，普通 view |
| 请求 / 规范化 wrapper | _balancesheet_vip_params / _balancesheet_row_transform，共用 helper |
| planner / 分页 | build_financial_statement_units / offset_limit / page_limit=5000 |
| 写入 / 交付 | raw_only_upsert / raw_with_serving_view |
| Ops 展示 | equity_financial（A股财务数据），顺序 40 |
| 观测及能力 | event_run_trace，audit=False；manual/schedule/retry，不接 workflow/probe |

### 必须保持的本表行为

- 单公告日或公告自然日闭区间，周末也生成 unit；不读股票池，不按股票逐只请求普通接口。
- report_type 缺失用默认全部，显式空或非法值拒绝；每日期只为所选真实类型生成 unit。请求只有 ann_date/report_type，字段与分页由通用 source client 提供。
- Raw 保存全部所选类型和不同身份版本，数值 nullable Numeric；三个日期为 Date，额外保存 source_content_hash、api_name、fetched_at，不重复保存 raw_payload。
- 七字段身份与 end_type 映射仅复用共享合同；同批同身份异内容失败，跨任务同身份修订覆盖，不按响应缺行删除旧事实。
- Serving 仅 report_type=1，先按 CASE 优先 update_flag=1，再按 f_ann_date 和稳定并列规则选择；不写独立 Serving 表，不在业务/页面重复选择逻辑。
- 普通自动任务使用 since_last_success_day_range 与显式类型数组；改变所选类型不会追溯历史日期，历史新增类型仍通过同一 maintain 区间处理。

资产负债表专属反例：同一主体的 f_ann_date=20260820 与 20260827 必须在 Raw 保留两个身份；Serving 在相同更新标志下选择较新的实际公告日，不能把 f_ann_date 从身份中省掉。

## 2. 源说明与历史样本

来源：doc_id=36，[本地资产负债表说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0036_资产负债表.md)。以下为原 2026-08-29～30 接入记录中的证据，本轮未重新请求源接口：

1. 全市场使用 `balancesheet_vip`，不得按股票池调用普通接口。
2. 2026 半年报范围项目 connector 分页为 `5000 + 5000 + 980 = 10980` 行。
3. 源文档列出 158 个输出字段；默认只返回 152 个，必须显式请求完整 158 字段。
4. `2026-08-28` 返回 1,457 行，八个前置字段均无空值，`comp_type` 包含 `1/2/3/4/7`。三张财务报表共用同一规范化契约：`end_type` 按 `end_date` 推导为 `1..4` 并校验一致性，但不进入七字段身份。
5. 实测同一 `002604.SZ + ann_date=20260820 + end_date=20260630 + report_type=1 + comp_type=1 + end_type=2 + update_flag=1` 出现两个不同 `f_ann_date`：`20260820` 和 `20260827`。因此 `f_ann_date` 必须进入 raw 身份；否则会覆盖掉源站两个版本。
6. 对 `600000.SH, period=20260630`，`report_type=1/6` 有数据，其他类型可为空。空类型不能判失败。

## 3. 迁移与实施位置

本表初始迁移为 [20260830_000164](/Users/congming/github/goldenshare/alembic/versions/20260830_000164_add_balancesheet_dataset.py)，保留当时建表、HDD 索引、普通 view 和八字段主键历史；后续 000166 改为七字段身份，000167 完成 end_type 非空规范化收口。**000166 nullable 只是历史中间状态，不是当前 ORM 或新的执行前提。**

完整原因、TaskRun 10189、116 行/空表中间审计、前向补齐的保护边界和禁止自动回退，见[三表迁移沿革](/Users/congming/github/goldenshare/docs/datasets/income-dataset-development.md#financial-statement-migration-history)。本表在那次中间审计时为空，不能据此推断今天无数据或跳过迁移执行时的校验。

[当前共享实现与消费者索引](/Users/congming/github/goldenshare/docs/datasets/income-dataset-development.md#financial-statement-implementation)承接原 LLD 的逐文件清单。planner、normalizer、Ops 标签/全选、手动与自动页面均已存在，不再保留“若另一张表先开发/需要新增共享控件”的分支。正常维护无需创建新 migration 或恢复旧 LLD 施工步骤。

## 4. 回归与验收

按[共用回归矩阵](/Users/congming/github/goldenshare/docs/datasets/income-dataset-development.md#financial-statement-regression)核对字段、输入、unit、分页、规范化、写入、view、迁移、Ops/UI 及排除边界；本表重点是 158 个完整源字段、150 个数值字段、上述专属样本及原始类型/版本保留。

入口为 [test_financial_statement_datasets.py](/Users/congming/github/goldenshare/tests/test_financial_statement_datasets.py) 与共用章节列出的 resolver/registry/Web/UI/架构测试。替身测试不证明真实数据库事务、当前源端分页或线上页面已验收；正式变更仍须按[数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)安排获准的真实对账。文档整理不扩大请求量、并发、API、字段或生产操作权限。

<a id="balancesheet-prod-acceptance-20260830"></a>

## 5. 初始范围 Prod 验收（历史）

2026-08-30 已完成 `2025-01-01 ~ 2026-08-31` 初始范围验收：

1. TaskRun `10215`、`10218` 均成功，合计完成 `7,296/7,296` 个 unit，写入 `115,177` 行，拒绝和失败 unit 均为 0；任务写入量与 `raw_tushare.balancesheet` 实际总行数完全一致。
2. raw 覆盖 6,334 个证券代码；身份空值、`end_type` 空值、非季度末、`end_type` 与 `end_date` 矛盾、非法内容指纹均为 0。
3. 全部 12 类报表均完成请求；源站实际返回类型为 `1/4/5/6/9/10/11/12`，其他类型为空结果，符合已确认的 empty-result 契约。
4. `core_serving.equity_balancesheet` 与 raw 的既定最新报表排序结果双向差集均为 0，每个 `(ts_code, end_date)` 唯一。
5. 源站返回已退市证券 `000583.SZ`（S*ST托普(退)）的资产负债表事实，而利润表无该代码；raw 按职责保留，不视为同步遗漏。
6. migration 已到 `20260830_000167`，表、主键及索引继续位于 `gs_raw_cold_hdd`；页面验收由运营确认通过。

该记录证明当时所列范围已验收；不证明全历史覆盖，也不证明此后每个公告日或当前生产状态已重新核验。
