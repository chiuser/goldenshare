# 公募基金列表（`fund_basic`）接入发现审计

状态：发现审计与 B2 LLD 完成，**B2-M1 与 B2-M2 隔离验证已通过；生产 migration 未应用，未创建任务、未写入远程数据**
首次审计：2026-08-03；复审：2026-08-06
截图菜单：基金列表
源文档：[公募基金列表](../sources/tushare/公募基金/0019_公募基金列表.md)

## 结论

`fund_basic` 是“基金列表”的明确接口，覆盖场内和场外基金。其 `benchmark` 是“某只基金当前业绩比较基准”的源端文本；它与独立的 [`mkt_idx_bmk` 基准指数库](fund-performance-benchmark-onboarding-discovery-audit.md) 是两类事实，不能互相替代。

全市场分页已验证：不传 `market`、25 个显式字段、`limit=2000` 从 offset `0` 连续到 `32000`，末页 342 行，合计 **32,342 个唯一 `ts_code`**。同一时点分别请求 E/O 得到 E=2,883、O=29,459；两者逐行多重集并集与无 market 分页完全一致。此前 15,000 行只是未分页单页上限，不能再表述为全市场基准。

## 源端事实与实测

| 项目 | 已核验事实 | 接入含义 |
| --- | --- | --- |
| 参数 | `ts_code`、`market`、`status`；无时间参数 | 主模型只能是快照，不能设计日期增量。 |
| 默认字段 | 25 个文档字段均返回 | 实现仍必须显式请求全部字段。 |
| 无业务参数、未分页 | 恰好 15,000 行，E/O 混合；与文档所称 `market` 默认 E 不一致 | 单页被截断，不能作为全量基准。 |
| `market=E` 分页 | `2000 + 883`；2,883 个唯一 `ts_code` | 场内分片翻至 short page。 |
| `market=O` 分页 | `limit=2000` 共 15 页：14 页满 2,000、末页 1,459；29,459 个唯一 `ts_code` | 场外分片翻至 short page。 |
| 无 market 分页 | `limit=2000` 共 17 页：16 页满 2,000、末页 342；32,342 个唯一 `ts_code` | 一个请求范围可完整枚举 E/O。 |
| 全集 A/B 对账 | 无 market 的25字段逐行多重集与显式 E+O 并集完全相等；缺失/额外均为0 | B2 可使用一个完整快照 unit。 |
| 单代码 | `510300.SH` 显式全字段返回 1 行 | `ts_code` 可作为手工精确查询，不证明全市场完整性。 |
| 分页 | 项目 connector 已验证第二页、后续 offset、short page 与 A/B 并集；当前 MCP schema 未暴露 `limit/offset` | Definition 使用 `offset_limit`，每页固定全量字段；分页证据以项目 connector 为准。 |

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
| 时间语义 | `none` / snapshot refresh；完整保存 E/O 源记录 | 无。 |
| 执行 unit | 一个不传 `market/status` 的完整分页快照 unit；`page_limit=2000`，short page 结束 | E/O 不得拆成两个 unit，否则现有 B0 writer 会让后一个 unit 覆盖前一个市场。 |
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
6. **LLD 已落实**：B2 使用一个完整 unit、B0 versioned direct-serving、HDD DDL、普通 schedule capability 和无 probe 契约；具体 schedule 频率继续由运营后置配置。

## B2 LLD 已关闭的前置证据

- E/O 与无 market 的项目 connector 分页、short page、25 字段、唯一代码集合和逐行多重集对账已完成。
- [B2 LLD](public-fund-b2-fund-basic-low-level-design-v1.md) 已固定单 unit、批次 E/O 完整性防护、表/索引 HDD DDL、direct-serving 和普通 schedule capability；不在代码中 seed 具体时间。
- 2026-08-06 已在全新隔离 PostgreSQL 18.4 实例验证 migration 缺少 `gs_raw_cold_hdd` 时 fail-closed、6 个 B2 relation 均绑定目标 tablespace，并完成一次 32,342 行真实完整快照：17 页、25 字段逐页显式请求、0 reject，source/current/observation key+hash 双向差集均为 0。隔离环境只证明 catalog placement，生产机械盘物理路径仍须在生产授权后复核。
