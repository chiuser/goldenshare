# 公募基金列表（`fund_basic`）接入发现审计

状态：发现审计完成，**未进入 LLD、未建表、未写入远程数据**
首次审计：2026-08-03；复审：2026-08-05
截图菜单：基金列表
源文档：[公募基金列表](../sources/tushare/公募基金/0019_公募基金列表.md)

## 结论

`fund_basic` 是“基金列表”的明确接口，覆盖场内和场外基金。其 `benchmark` 是“某只基金当前业绩比较基准”的源端文本；它与独立的 [`mkt_idx_bmk` 基准指数库](fund-performance-benchmark-onboarding-discovery-audit.md) 是两类事实，不能互相替代。

场外全市场分页已验证：`market=O`、25 个显式字段、`limit=2000` 从 offset `0` 连续到 `28000`，末页 1,447 行，合计 **29,447 个唯一 `.OF` 代码**。本结论同时由 `tushareMcp` 和项目 `TushareHttpClient` 验证；此前 15,000 行只是未分页单页上限，不能再表述为场外范围阻断。

## 源端事实与实测

| 项目 | 已核验事实 | 接入含义 |
| --- | --- | --- |
| 参数 | `ts_code`、`market`、`status`；无时间参数 | 主模型只能是快照，不能设计日期增量。 |
| 默认字段 | 25 个文档字段均返回 | 实现仍必须显式请求全部字段。 |
| 无业务参数 | 15,000 行：E 1,174、O 13,826；与文档所称 `market` 默认 E 不一致 | 默认请求既被截断，又不是稳定市场口径。 |
| `market=E` | 2,879 行，完整返回当前样本 | 场内范围看似未触顶，仍须以项目 connector 再验证。 |
| `market=O` 分页 | `limit=2000` 共 15 页：14 页满 2,000、末页 1,447；29,447 个唯一 `.OF` | 场外全市场可由 `offset_limit` 完整枚举。 |
| 单代码 | `510300.SH` 显式全字段返回 1 行 | `ts_code` 可作为手工精确查询，不证明全市场完整性。 |
| 分页 | MCP 实际接受未列出的 `limit/offset`；项目客户端同样验证到 short page | Definition 使用 `offset_limit`，每页固定全量字段。 |

已确认、后续 Definition 必须原样使用的 `source_fields`：

```text
ts_code, name, management, custodian, fund_type, found_date, due_date,
list_date, issue_date, delist_date, issue_amount, m_fee, c_fee,
duration_year, p_value, min_amount, exp_return, benchmark, status,
invest_type, type, trustee, purc_startdate, redm_startdate, market
```

`ts_code` 是候选身份键；所有日期、费用、状态和 `benchmark` 均可能为空，不能作为 required field。`status` 实测还出现 null，不能把 `L/D/I` 写成排他校验。

## 建议的接入轮廓（非 LLD）

| 维度 | 当前建议 | 不能提前决定的内容 |
| --- | --- | --- |
| 时间语义 | `none` / snapshot refresh；全市场至少包含场外 O，并以 E/O 市场作为源端分片 | 无。 |
| 执行 unit | 每个市场一个完整分页快照 unit；不传 `status`，保留源端返回的上市、发行、摘牌和空状态记录 | 不可用无参数单页充当全量基准。 |
| freshness / completeness | 不做连续日期 audit；只观察最近成功快照 | 快照刷新频率和源站发布时点尚无证据。 |
| 存储 | 所有业务字段均必须落表；物理表、所有叶分区和索引固定落 HDD tablespace `gs_raw_cold_hdd`，禁止落 SSD | direct-serving / raw->serving 在 LLD 固化。 |
| Ops/UI | 新建“公募基金”分组，不复用“ETF基金”；支持手动任务和普通定时自动任务，不接 probe | 需在 Definition/自动化契约中保证页面不暴露 probe。 |

当前仓库只有 ETF 专用的 `fund_daily` / `fund_adj` / `etf_*`，没有 `fund_basic` 的 Definition、DAO、表、动作或前端条目；不得把 ETF 活跃池当成公募基金全量代码池。

## 已定口径与剩余设计门禁

1. **场外全市场与字段完整性已定**：O 市场必须全量分页；全部 25 个源字段均保存，`source_fields` 固定显式请求。
2. **状态范围已定**：不以 `status` 过滤，原样保存所有源端状态和值。
3. **业绩基准文本**：`benchmark` 作为本表源字段原样保存；它不是可结构化解析出的基准库主键。独立 `mkt_idx_bmk` 仍按自己的源端事实接入，不能以它替代本字段。
4. **Ops 与物理存储已定**：归入“公募基金”；仅手动 + 普通定时任务、无 probe；所有叶分区及索引放 HDD。
5. **身份与历史版本已定**：逻辑身份为 `ts_code`。维护当前记录，并为同一 `ts_code` 的源字段内容变化保留观察版本；每个版本保存全部 25 个源字段、内容散列和首次/最后一次观察时间。观察历史只能从接入日开始追溯，观察时间不是源端生效时间。
6. **仍需 LLD 落实**：共享的 versioned direct-serving 写入契约、HDD DDL、快照频率，以及不影响 freshness 语义而彻底隐藏/拒绝 probe 的通用自动化契约。

## 进入 LLD 前必须补的证据

- 为 E/O 两个市场补历史规模、字段端到端、写入量和 short-page 证据。
- 在 LLD 中固定表/分区/索引 HDD DDL、快照频率、direct-serving 写入路径与普通定时任务时间。
