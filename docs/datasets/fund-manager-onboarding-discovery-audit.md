# 基金经理（`fund_manager`）接入发现审计

状态：**B3-M0、LLD 审计与 B3-M1 本地实现/验证通过；B3-M2 尚未开始，未应用迁移、未写入数据库或创建任务**
首次审计：2026-08-03；源端复审：2026-08-06
截图菜单：基金经理
源文档：[基金经理](../sources/tushare/公募基金/0208_基金经理.md)
正式设计：[公募基金 B3：基金经理 LLD v1](public-fund-b3-fund-manager-low-level-design-v1.md)

## 1. 审计结论

`fund_manager` 当前适合按**一个无业务参数的全量快照 unit** 接入：每次显式请求全部 10 个源字段，以 `limit/offset` 持续分页到 short page，再整体替换 current 并更新 observation。当前证据不支持把 `ann_date`、`ts_code`、`name` 或未文档化的日期区间暴露为运营输入。

本轮已补齐旧审计缺失的 short-page 证据。2026-08-06 实测全集为 84,357 行：`limit=5000` 为 `16×5000 + 4357`，`limit=4000` 为 `21×4000 + 357`，两次结果的完整 10 字段行多重集完全一致。该行数只是一时点基线，不是永久 SLA。

B3-M0、后续 LLD 审计与 B3-M1 本地实现/验证均已通过。无参单 unit 全量快照、5,000 行分页、批内任职身份唯一性和 B0 writer 容量/事务阈值均已落到代码与自动化；隔离 PostgreSQL 容量、HDD 和五段对账仍属于 B3-M2。

## 2. 源端契约

### 2.1 参数与权限

| 项目 | 文档 / 实测事实 | 接入含义 |
| --- | --- | --- |
| 接口 | `fund_manager` | 公募基金经理任职及简历事实，不是带稳定人员 ID 的人物主表。 |
| 权限 | 文档口径 500 积分可调，2,000 积分以上可提高频次 | 上线前仍按生产 token 做最小真实验收。 |
| 对象过滤 | `ts_code` 可选，支持逗号分隔；`name` 可选 | 过滤结果只能用于查询/诊断，不能替换全量 current，也不暴露给运营任务。 |
| 日期过滤 | 仅有单点 `ann_date=YYYYMMDD` | 它是公告日期点过滤，不是任职生效日期，也不提供区间能力。 |
| 分页 | `limit`、`offset`；文档单次上限 5,000 | 使用 `offset_limit`，只有 short page 才表示完成，不设置最大页数。 |
| 文档差异 | 本地源文档把 `offset` 类型写成 `intint`，MCP schema 写成字符串；项目 connector 用整数 offset 已实测成功 | 实现沿用项目通用整数 offset；LLD 测试覆盖第二页和 short page，不传播文档笔误。 |

未文档化日期区间的反向验证：请求 `start_date=20260101, end_date=20260131, limit=100` 时，返回的 100 行与无日期参数前 100 行顺序及内容完全相同，且 98 行公告日期落在请求区间外。结论是源端**静默忽略**这两个参数，禁止生成或暴露 `start_date/end_date`。

### 2.2 显式 source fields

每一页固定显式请求并原样保存：

```text
ts_code, ann_date, name, gender, birth_year, edu, nationality,
begin_date, end_date, resume
```

MCP `limit=5` 小样本中，默认字段与显式 10 字段结果一致；项目 connector 的 84,357 行全集中，每行都存在这 10 个字段键。默认返回一致只作为校验证据，生产请求仍必须显式传 `source_fields`。

源文档把 10 个输出字段全部定义为 `str`。B3 不对出生年份、公告日期、任职日期做数值化或日期推导；模型应保存原始文本/空值，并另行通过校验约束非空身份字段的格式。

## 3. 真实请求证据

### 3.1 分页完整性与性能基线

| 请求 | 页大小 | 页数 | 总行数 | 源请求耗时 | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| 无业务参数、显式 10 字段 | 5,000 | 17 | 84,357 | 4.840 秒 | 最后一页 4,357，正常 short page |
| 无业务参数、显式 10 字段 | 4,000 | 22 | 84,357 | 5.359 秒 | 最后一页 357，正常 short page |

两组全量结果：

- 完整行多重集完全一致；双向差集均为 0。
- 完全相同的源行重复组为 0，重复多余行数为 0。
- 5,000 行页已得到源文档上限与真实请求双重支持，并已在 LLD 固定为正式页大小；不把当前 17 页固化成最大页数。
- 当前项目 `DatasetSourceClient` 会把全部页累积到 `rows_raw`；本次全量 JSON 紧凑序列化约 43.34 MB，仅源请求约 5 秒。真实 Python 内存和数据库事务耗时会更高，必须在 B3 实现阶段单独压测，不能把本次请求耗时当成端到端 SLA。

### 3.2 过滤语义

| 过滤 | 请求结果 | 与无参全集子集对账 |
| --- | ---: | --- |
| `ts_code=000001.OF` | 19 行 | 完整行多重集一致 |
| `name=吴昊` | 134 行 | 完整行多重集一致 |
| `ann_date=20251231` | 139 行 | 完整行多重集一致 |
| `ts_code=000001.OF,070003.OF` | 38 行 | 与两只基金子集并集一致 |

MCP 另行验证 `ann_date=20260617` 为 89 行，所有行的 `ann_date` 都匹配；但其中 5 行 `begin_date` 为空，另有 5 行的 `begin_date` 晚于公告日。它证明公告点过滤有效，也证明公告日不能当作任职生效日。

过滤能力不等于任务输入能力。局部请求无法证明已覆盖晚到修订、离任日期回填或旧公告记录改写，因此 B3 主同步仍采用无参完整快照。

## 4. 数据形态、空值与容量

2026-08-06 全量样本：

| 项目 | 数量 / 范围 |
| --- | --- |
| 总行数 / 基金代码 / 姓名 | 84,357 / 32,288 / 7,032 |
| 公告日期 | 1999-04-22 至 2026-08-05；空值 0 |
| 任职开始日期 | 1998-03-27 至 2026-08-05；空白或空值 1,062 |
| 任职结束日期 | 1999-06-30 至 2026-08-06；空白或空值 38,456 |
| 出生年份 | 空白或空值 78,555，仅 5,802 行具备非空 `name + gender + birth_year` |
| 国籍 | 空白或空值 10 |
| 简历 | 空值 0；合计 10,049,928 字符；最长 728 字符；P95 约 214 字符 |

日期字段保存 Tushare 原始 `YYYYMMDD` 文本和空值，不把空值解释成日期，也不根据公告日推导任职日期。`resume` 使用可容纳全文的文本字段，不截断、不摘要、不拆词后替代原文。

## 5. 任职事实身份与跨基金聚合

### 5.1 源任职事实

全量冲突审计结果：

| 候选身份 | 重复组 | 内容冲突组 | 结论 |
| --- | ---: | ---: | --- |
| `(ts_code, ann_date, name)` | 419 | 419 | 不可用；同一次公告中确实存在同基金同姓名但不同 `begin_date` 的两条源事实。 |
| `(ts_code, ann_date, name, begin_date)` | 0 | 0 | 当前全集唯一，继续作为 source entity 候选。 |
| `(ts_code, name, begin_date)` | 0 | 0 | 当前也唯一，但丢失公告事实，不优于四字段口径。 |

因此 `begin_date` 即使为空也必须原样参与 source entity key；不能为了规避空值把它从身份中删除。正式 LLD 已固定由这四个原始字段生成稳定 `source_entity_key`，并以全部 10 个源字段生成 `source_content_hash`，消费 B0 的 current + observation contract，不另造一个会与共享 contract 并行漂移的 `assignment_id` 真相源。

若未来真实同步出现同一四字段身份对应多条不同内容，必须 fail closed 并保留冲突样本，不能静默覆盖、任选一行或截断。

### 5.2 跨基金人员聚合

已冻结口径保持不变：

1. 源事实对象是“某基金的一条经理任职记录”，不是全局人物主表；全部 10 个 Tushare 字段原样保存。
2. 仅当 `name`、`gender`、`birth_year` 三者都非空时，派生可空的 `manager_identity_key = hash(normalized(name, gender, birth_year))`。
3. `birth_year` 缺失时 `manager_identity_key = NULL`，任职事实照常保存，但不自动跨基金合并。
4. 派生身份只供查询聚合，不改写、合并或替代 Tushare 任职事实。

当前只有 5,802 / 84,357 行可生成该身份，共 738 个非空派生身份；其中 605 个出现在多只基金，单个身份最多关联 73 只基金。这说明派生字段确实有跨基金查询价值，也说明绝不能把缺出生年份的 78,555 行按姓名强行合并。

## 6. 当前代码上下文与复用边界

当前代码已新增 `fund_manager` Definition、身份转换、默认关闭且仅 B3 启用的批内唯一键门禁、显式 current/observation 模型、既有观察快照 DAO 注册、HDD migration、Ops Catalog/freshness 接入和专项测试；当前 Alembic head 为 `20260806_000127`。前端仍只消费既有 Catalog/automation capability contract，没有新增分组或 action-key 白名单。

现有能力的真实语义如下：

- `DatasetSourceClient` 已支持整数 `limit/offset`、逐页显式携带 `source_fields`、short-page 终止和源错误重试；但它会把全部页累积到 `rows_raw`。
- B0 的 `serving_observed_snapshot_refresh` 已支持 current 整体替换、observation 观察时间更新，并对空快照、任一 normalize reject、缺 source field、完全重复的 `(source_entity_key, source_content_hash)` fail closed。
- B0 writer 当前以“实体键 + 内容哈希”作为重复判断，因此**不会**拒绝“同一 `source_entity_key`、不同内容哈希”的两行；它会把两行都视作可表示的当前源事实。B3 的四字段身份当前没有这种冲突，但 M0 已把未来冲突定义为失败条件。正式 LLD 已将最小门禁固定为默认关闭、仅 B3 opt-in 的批内唯一键质量契约；不假装 B0 已经提供，也不改变 B1/B2 的既有语义。
- B0 没有提供 `manager_identity_key`，该字段是 B3 的纯派生查询字段，不应被提升为通用“基金人物框架”。

因此，B3 可以复用 B0 的观察快照持久化协议和现有分页 client，但并非零新增语义；身份唯一性与 84,357 行容量是 LLD 的两个明确门禁。

## 7. B3 LLD 已固定的边界与门禁

| 维度 | LLD 固定口径 |
| --- | --- |
| 时间输入 | `date_axis=none`、`input_shape=none`、一个无业务参数全量快照 unit；不暴露 `ann_date` 或日期区间。 |
| 分页 | `offset_limit`、`page_limit=5000`、并发 1、无最大页数；每页显式 10 字段，short page 才成功。 |
| 完整性 | 空结果、任一 reject、缺字段、同四字段身份重复/冲突、未到 short page 均不得替换 current；以默认关闭、B3 opt-in 的 `batch_unique_key_fields=("source_entity_key",)` 补足 B0 门禁。 |
| 存储 | direct-serving 的 current + observation；全部源字段和派生审计字段；表与全部索引固定 `gs_raw_cold_hdd`，WAL 保持 SSD。 |
| Ops | “公募基金”分组；手动、普通 cron/once 定时和重试；无 filters、无 probe、无 workflow、无自动 schedule seed。 |
| freshness / audit | `bucket_rule=not_applicable` 仅表示不按连续业务日期做 completeness；本数据集同时明确不支持时间输入。 |
| 性能门禁 | M2 至少以 84,357 行并另加 100,000 行容量 fixture 验收；专用进程峰值 RSS 同时不超过 1 GiB 和起始 `MemAvailable` 的 25%，DB 事务不超过 180 秒，unit 端到端不超过 240 秒，并通过两处 rollback 故障注入。 |

## 8. 已拍板项与延后运营决策

1. 主同步已固定为每次无业务参数的完整快照，一个 unit 翻页至 short page 后一次事务提交。
2. 页大小固定 5,000，不设置最大页数或行数上限。
3. 同一 `source_entity_key` 的单批重复/冲突由 opt-in quality contract 在 normalizer fail closed；不改变 B0 writer 与 B1/B2 的全局语义。
4. 84,357/100,000 行的内存、事务和原子回滚阈值已写入正式 LLD，必须在隔离 PostgreSQL 实测后才能进入生产。
5. 自动任务实际频率与 cron/once 时间继续延后。它不影响 B3 编码、隔离验证或首次生产同步；B3 不自动创建任务。

## 9. 当前禁止项与下一步

- 禁止把 `ann_date` 当成任职生效日期，禁止生成会被源端静默忽略的 `start_date/end_date`。
- 禁止按姓名，或按姓名加空出生年份，自动合并不同基金的经理。
- 禁止截断 `resume`，禁止只拉第一页，禁止设置固定最大页数后把截断当成功。
- 禁止局部过滤结果替换全量 current，禁止未完成所有页或存在 reject 时提交业务数据。
- B3-M1 已完成；未经 B3-M2 授权，禁止在隔离 PostgreSQL 应用迁移或写入数据；生产迁移与首次同步仍需后续单独授权。

下一步是在用户授权后进入 B3-M2：在隔离 PostgreSQL 应用 migration，核验 HDD placement，以 84,357 行真实基线和 100,000 行容量 fixture 验收 RSS/耗时/单事务回滚，并完成最小真实同步五段对账；不得提前创建 schedule。
