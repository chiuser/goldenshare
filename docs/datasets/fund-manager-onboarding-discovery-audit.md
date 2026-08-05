# 基金经理（`fund_manager`）接入发现审计

状态：发现审计完成，**未进入 LLD、未建表、未写入远程数据**
首次审计：2026-08-03；复审：2026-08-05
截图菜单：基金经理
源文档：[基金经理](../sources/tushare/公募基金/0208_基金经理.md)

## 结论

`fund_manager` 是九项中唯一已由 MCP 证明支持 `limit/offset` 的接口。它可作为分页快照同步候选；`ann_date` 也能精确取事件增量（2026-06-17 为 89 行）。但当前尚未证明公告日增量能覆盖补发、修订和离任更新，因此不能直接承诺“每日只按公告日增量”。

## 源端事实与实测

| 项目 | 已核验事实 | 接入含义 |
| --- | --- | --- |
| 参数 | `ts_code`、`ann_date`、`name`、`limit`、`offset` | 代码/姓名可做查询过滤，不能自动成为运营输入。 |
| 默认 / 显式字段 | 10 个默认字段；单代码显式全字段仍为 10 个 | 必须固定显式字段。 |
| 无业务参数分页 | `limit=2, offset=0/2` 与 `limit=4` 的 4 个身份键集合完全相等 | `offset_limit` 可作为候选分页策略。 |
| 大页 | offset 0..20,000 均可取到分页记录；当前只是已验证前 22,000 行，不是全量总数 | 正式同步须继续到 short page 并记录总页数。 |
| 日期点 | `ann_date=20260617` 返回 89 行 | 日期是公告事件过滤，不证明连续每日都有数据。 |

候选 `source_fields`：

```text
ts_code, ann_date, name, gender, birth_year, edu, nationality,
begin_date, end_date, resume
```

前 22,000 行样本中，20,636 行 `birth_year` 为空；源端没有经理 ID。`(ts_code, ann_date, name, begin_date)` 是任职源事实的候选身份，不能把姓名或姓名加空出生年当作跨基金的个人主键。

## 建议的接入轮廓（非 LLD）

| 维度 | 当前建议 |
| --- | --- |
| 初始同步 | `none` / 全量分页快照，直至 short page；每页都携带完整 `source_fields`。 |
| 后续更新 | 在完成“公告日不漏补发/修订”的验证前，继续受控全量快照；之后再评估 `ann_date` point/range。 |
| freshness / audit | 不做连续日期 completeness；可观测最近成功快照或最近公告日。 |
| 事务 | 一个完整 page-merged snapshot / 明确事件 unit 一次写入；LLD 必须评估简历文本内存和写入量。 |
| 存储与 UI | 全部 10 个字段均保存，物理表、叶分区和索引固定 HDD；使用新“公募基金” Ops 目录，且不复用 ETF 活跃池。 |

现有代码没有此接口。通用 `DatasetSourceClient` 会按照 Definition 追加 `limit/offset`，所以 LLD 必须用项目实际 connector 完成第二页、short page 和页合并唯一键对账，不能只沿用本次 MCP 小页证明。

## 已冻结的任职事实与跨基金聚合口径（非 LLD）

1. **源事实先行**：建立的事实对象是“基金经理任职记录”，不是全局人物主表。每条任职保留全部 10 个 Tushare 字段；候选源身份为 `(ts_code, ann_date, name, begin_date)`，物理表使用自身 `assignment_id`，同身份内容变化保留观察版本。
2. **跨基金聚合不改写源事实**：仅当 `name`、`gender`、`birth_year` 三者都非空时，写一个可空系统字段 `manager_identity_key = hash(normalized(name, gender, birth_year))`。跨基金统计以该字段 `GROUP BY` 任职事实完成，不另造或覆盖 Tushare 人物记录。
3. **出生年份缺失**：`manager_identity_key = NULL`，任职事实仍完整保存，但不自动跨基金归并；这避免把同名经理误认成同一人。
4. `resume` 全文必须保存；是否默认在前端展示不影响源事实存储，留待 LLD 的查询/UI 设计决定。

## 2026-08-05 批次固定约束

每次请求固定显式 `source_fields`，所有源端返回字段完整保存；Ops 归入“公募基金”，仅支持手动和普通定时自动任务，不接 probe；所有物理数据对象固定 HDD。
