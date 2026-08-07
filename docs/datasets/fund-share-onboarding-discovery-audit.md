# 基金规模（`fund_share`）接入发现审计

状态：**B4-M0、B4-FS-M1、B4-FS-M2 与 B4-FS-M3 均已通过。生产 migration/HDD placement、正式 TaskRun `#7556` 首次最小同步及独立完整对账已闭环；未创建 schedule、probe、workflow，也未执行历史回补。**
首次审计：2026-08-03；本轮复审：2026-08-07
截图菜单：基金规模
源文档：[基金规模数据](../sources/tushare/公募基金/0207_基金规模数据.md)（doc_id=207）

## 1. 审计结论

`fund_share` 是公募基金份额/规模变动的带日期源事实，不是基金净值或基金主数据。下列两项纠偏已写入正式 LLD，并在 B4-FS-M1 至 M3 中完成实现与验收：

1. **区间请求支持分页。** 两日和七个自然日样本均已用项目实际 connector 证明：区间 `limit/offset` 分页结果与逐日结果完整行多重集一致。逐日 unit 是为了限制单事务、隔离失败和支持单日补录，不是因为区间分页会漏数。
2. **日期轴必须是自然日。** 周日 2026-07-05 返回 6 条 O 市场记录；按交易日历展开会真实漏数。自然日零行是合法情况，不应判为缺失或同步失败。

接入仍固定全市场、不传 `market` 过滤、显式请求并保存全部六个 source fields。O 不是可选扩展，而是完整源范围的一部分。

## 2. 源接口真实行为验证

### 2.1 请求矩阵

| 请求形态 | 实际请求与行数 | 分页/对账证据 | 结论 |
| --- | --- | --- | --- |
| 无业务参数 | 显式六字段返回 2,000 行，日期 20260805..20260812，只有 SH/SZ | 命中单次上限 | 不能作为全量快照或完整基准。 |
| 只传对象 | `ts_code=510300.SH` 返回 2,000 行，日期 20180528..20260806 | 命中单次上限 | 对象过滤不是完整历史维护路径。 |
| 单日点 | 20260616=1,664；20260617=1,652 | `limit=1000` 分别为 `1000/664`、`1000/652` | point + offset/limit 可完整拉取单日。 |
| 两日区间 | 20260616..17=3,316 | `limit=1000` 为 `1000/1000/1000/316`；`limit=777` 为 `777/777/777/777/208`；两者与两个 point 并集相同 | 区间分页真实有效。 |
| 七个自然日区间 | 20260701..07=8,393 | `1000`×8+`393`；与七个 point 行多重集及 SHA-256 摘要完全一致 | 短区间分页完整；不代表任意宽区间适合作为一个事务。 |
| 市场 O | `trade_date=20260617, market=O` 返回 7 行 | 与无 market 的同日 O 子集一致 | 源端接受 O，生产主链不得只枚举 SH/SZ。 |
| 自然日边界 | 20260704=0；周日 20260705=6，且全为 O | 七日区间与逐日并集一致 | 零行合法；自然日不可按开市日裁剪。 |

### 2.2 字段矩阵

| 请求 | 实际列 | 结论 |
| --- | --- | --- |
| 不传 `fields` | `ts_code,trade_date,fd_share,fund_type,market` | 与官方页面和 MCP 元数据所写前三列不一致，不能依赖默认字段。 |
| 显式官方三字段 | `ts_code,trade_date,fd_share` | 会主动丢掉其他已知字段。 |
| 显式全部六字段 | `ts_code,trade_date,fd_share,total_share,fund_type,market` | Definition 必须固定使用这一顺序，每一分页都携带。 |

七日样本中 `total_share` 8,393 行全部为空，`fund_type` 为空 473 行；这证明二者必须 nullable，不代表可以不请求、不建列。`ts_code/trade_date/fd_share/market` 无空值。

### 2.3 身份、冲突与样本规模

1. 两日 3,316 行、七日 8,393 行中 `(ts_code, trade_date)` 均完全唯一，没有相同实体键的重复或内容冲突。
2. 七日市场为 SH/SZ/O=`4,766/3,584/43`，代码后缀与市场映射全部一致；身份仍以 `(ts_code, trade_date)` 为准，`market` 必须保真但不需要进入实体键。
3. 七日 `fund_type` 除 ETF/空值外还出现 `(带固定封闭期)`，不能写死 ETF 枚举。
4. 单日峰值样本为 1,696 行，紧凑 JSON 约 0.20 MB；七日区间为 8,393 行、约 1.00 MB。`page_limit=2000` 可减少日常请求，但必须保留无页数上限、短页结束的通用分页。
5. 历年同日抽样行数从 2011 年 66 行增长到 2026 年 1,673 行；任何历史回补授权前仍须做逐年只读容量预算，不能用当前单日乘固定年数冒充精确规模。

## 3. 三层时间语义

| 层 | fund_share 口径 |
| --- | --- |
| 时间输入 | 运营提交一个自然日 point，或自然日起止 range；字段仍使用平台通用 `trade_date/start_date/end_date`。 |
| 执行 / unit | point 生成一个全市场日期 unit；range 必须按每个自然日展开，每个日期独立分页、归一化、写入和提交。不得传 SH/SZ/O 过滤，也不按基金池展开。 |
| freshness / audit | `date_axis=natural_day`，但 `bucket_rule=not_applicable`、`audit_applicable=false`；这只退出“每天必须有数据”的连续桶审计，不取消日期输入或逐自然日执行。 |

逐日执行是工程边界：当前单 unit 约 0.20 MB、约 1,700 行，可把任何页失败、reject、冲突和事务回滚限制在一天。宽区间分页虽然已证明可用，但随历史跨度线性扩大内存和数据库事务，不作为主执行 unit。

## 4. 当前代码与影响面审计

| 消费方 | M0 发现 | B4 已落地结果 |
| --- | --- | --- |
| Definition/registry | M0 时 `public_fund.py` 只有 B1/B2/B3 四项 | 已新增 `fund_share`；六字段、natural-day point/range、无 filters、分页 2,000。 |
| resolver/unit planner | generic 对 `natural_day + not_applicable/every_natural_day` 的 range 原先只生成一个无锚点 unit | 未改 generic 全局行为；新增 Definition 显式选择的自然日 point-fanout builder，避免影响其余 Definition。 |
| request builder | `_daily_params` 已按 anchor 生成单一 `trade_date`，且未配置 filter 时不会产生 `ts_code` | 可复用；不得使用会在 range 下生成 `start_date/end_date` 的 `_trade_date_or_start_end_params`。 |
| source client | `offset_limit` 每页都携带 `definition.source.source_fields`，短页结束，无最大页数 | 直接复用；Definition 固定 `page_limit=2000`、并发 1。 |
| normalizer | 支持日期/Decimal、unit date 一致性和 batch 唯一键 fail-closed | `trade_date` 与 `fd_share/total_share` 归一化；要求 `ts_code/trade_date/fd_share/market/source_entity_key`，按 source_entity_key 检查完全重复与冲突。 |
| B0 snapshot writer | 会清空并整体替换 current；空快照必须失败 | 未复用为 fund_share 写路径；新增显式 opt-in 的 scoped observed-fact writer，合法空日 0 行成功且不删除历史。 |
| ORM/DAO/migration | M0 时尚无 fund_share 表或 DAO | 已落 direct-serving current + observation、全字段与观察元数据、非分区 HDD 表/索引，并完成隔离与生产 migration 验收。 |
| Ops Catalog/UI | “公募基金”分组已存在，M0 时顺序到 fund_manager=40 | 已增加 fund_share=50；手动页面由 date model 显示自然日 point/range，未新增前端 dataset-key 字段白名单。 |
| 自动任务 | schedule-only capability 已存在；`trigger_day_point` 原先由后端和前端各自维护 news/major_news 白名单 | 已将 calendar-policy 收敛到 Definition/API capability contract，运行时验证和前端渲染消费同一契约；本轮未创建 fund_share schedule。 |
| workflow/probe | workflow 显式定义，不会因新增 Definition 自动加入；probe capability 由 resolver 决定 | 不加入 workflow、不提供 probe；后端必须拒绝 probe/fallback。 |
| freshness/cards/audit | target ORM 与 observed_field 驱动数据状态；`not_applicable` 不进入日期完整性任务 | freshness 采用事件/运行轨迹，而非连续开市日；卡片展示 serving 表且无伪 raw 表。 |

本轮 CodeGraph 覆盖：`DatasetUnitPlanner`、request builders、`DatasetSourceClient`、normalizer、B0 writer/DAO、Definition registry、Ops catalog/manual action、schedule capability/validation/runtime、前端自动任务 calendar-policy 消费者、freshness/date audit。未发现需要修改 biz 或 lake 子系统。

## 5. LLD 硬约束

1. source fields 固定为 `ts_code,trade_date,fd_share,total_share,fund_type,market`，六列全部落库；所有分页显式传 fields。
2. 全市场请求不带 `market`、`ts_code` 或基金池过滤；SH/SZ/O 全部保留。
3. point/range 都支持，但 range 在 resolver/planner 展开为逐自然日 point unit；每 unit `offset_limit`、`page_limit=2000`、并发 1、短页结束、无最大页数。
4. 每行实际 `trade_date` 必须等于 unit anchor；非空日任何 reject、缺字段、重复实体键或内容冲突都使该日 unit 整体失败并回滚。
5. 空自然日是成功 no-op：不得写入、不得删除其他日期、不得制造缺数问题。
6. direct-serving 保存当前事实与接入后的观察版本；逻辑实体为 `(ts_code, trade_date)`，内容散列覆盖全部六个 source fields。
7. 不能复用“整体替换 current”的 B0 snapshot writer；新 observed-fact contract 必须是显式 opt-in，不改变 B1/B2/B3 语义。
8. 两张非分区业务表和全部索引显式落 `gs_raw_cold_hdd`；PostgreSQL WAL 保持 SSD。
9. Ops 位于“公募基金”；支持手动、cron/once、retry；不支持 workflow、probe 或自动 seed。实际 schedule 频率与创建继续由运营后续拍板，不阻塞代码接入。
10. 自动任务的触发日策略必须由 API capability 单一事实驱动，禁止新增 fund_share 前后端双白名单。

## 6. B4-M0 结论与下一步

B4-M0 已通过，[正式 LLD](public-fund-b4-fund-share-low-level-design-v1.md) 已冻结三项新增能力的最小边界：Definition 显式 opt-in 的自然日逐日 unit、按日期作用域原子替换 current 的观察型时序事实 writer/DAO、由 Definition/API 单一事实驱动的自动任务 calendar-policy capability。三项均不得用 `fund_share` key 分支改变无关数据集。

LLD 最终选择非分区 HDD current/observation 表，以保留 `(source_entity_key, source_content_hash)` 版本主键和 current `source_entity_key` 唯一防线；同时规定空自然日成功 no-op，非空日按日期完整替换 current，observation 保留接入后的内容版本。该设计已完成 M1–M3；实际 cron 时间、历史回补起止日期和 B4 后续 `fund_div` 仍须分别拍板。

B4-FS-M2 的真实证据为：2026-07-04 `0/0/0/0/0/0` 合法 no-op；2026-07-05 fetched/accepted/written/current/observation 均为 6、reject 0 且全部为 O；2026-07-07 五段行数均为 1,673、reject 0，SH/SZ/O=`953/718/2`。源端、归一化、current、observation 的实体/内容散列与市场分组一致；相同快照重跑不增加 current/observation 版本。10,000 行分页、资源门禁、两处故障回滚和 PostgreSQL 同日期 advisory lock 也均通过，详细证据见 LLD 13.2。

B4-FS-M3 已在生产完成：migration head=`20260807_000128`，10 个 relation 均位于真实 HDD tablespace；正式 TaskRun `#7556` 对 `2026-07-07` 同步成功，source/accepted/written/current/observation 均为 1,673、reject 0，SH/SZ/O=`953/718/2`。独立复核的 source/current/observation 摘要一致、六向差集与目标散列错误均为 0。详细证据见 LLD 13.3。

下一步可单独拍板 `fund_div`，或进入 B4-FS-M4 的历史规模只读预算、回补及 schedule 决策；三者互不自动授权。
