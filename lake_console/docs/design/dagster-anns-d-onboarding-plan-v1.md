# 上市公司公告接入 DG 技术方案 v1

状态：P0 契约与预算核验完成，P1 待开发；2026-10-04 用户已确认业务决策。本文件不表示数据集已经注册、bootstrap 已执行或调度已启用。

对应 [代码级 LLD](dagster-anns-d-onboarding-low-level-design-v1.md)。先完成本数据集，再迁移下载器消费来源，最后设计和实现数据中心页面。后两项不属于本轮开发范围。

## 1. 目标与已确认决策

在 DG 保存 Tushare `anns_d` 的业务元数据，形成可按公告日期查询的 Raw Parquet 数据集。历史从 Prod 初始化，此后直接从 Tushare 更新；不建立公告 PostgreSQL 副本。

2026-10-04 用户确认：

1. Bootstrap 范围为 2020-01-01 至 2026-09-30，闭区间。
2. 更新合并已有与新返回记录，只删除六字段完全相同的重复。源端本次未返回的旧记录保留。
3. 北京时间每天 08:00 更新最近七个已结束自然日，包含昨天；支持手工历史区间补拉。
4. 首期只交付 Raw、bootstrap、每日更新、checks、取消与续跑。不新增 Silver/Gold、搜索索引、下载器改动或前端。

七天是维护窗口，不是源端迟到 SLA。调度停机超过窗口时必须显式补齐缺口，不能假定下一次七天回看足够。

## 2. 依据与当前事实

依据：[正式接入模板（含 §7A）](../templates/dagster-dataset-onboarding-template.html)、[性能治理](dagster-data-pipeline-performance-governance.md)、[编码规范](../../orchestrator/CODING_STANDARDS.md)，及根、lake_console、orchestrator AGENTS。

源文档：doc_id=176，[上市公司全量公告](../../../docs/sources/tushare/大模型语料/0176_上市公司全量公告.md)。文档单页上限 2,000，MCP 描述为 6,000，现阶段采用有依据的较小值 2,000，不据工具简介扩大请求。

当前代码证据：

- DG `defs/catalog/lake_assets.py`、`definitions.py` 静态检索未发现公告资产实现；架构文档中的规划项不代表已接入。
- `defs/resources.py` 的 TushareResource 要求显式 fields；ProdPostgresResource 提供只读事务；DuckDBResource 提供受控连接。
- `defs/tushare_api_io.py::_fetch_all_pages` 会累积全部分页，不作为本数据集流式执行器。
- `defs/prod_db/daily_basic.py` 是明确投影及有界读取参考，但它的交易日、非空键和字段转换不能套到公告。
- 现有下载器只读 Prod，写本机 SQLite 台账。后续迁移单独设计；本轮不改变 CLI。

[2026-10-03 Prod 审计](../../../reports/anns_d_prod_sync_audit_20261003.md)覆盖 2,465 个自然日：12,064,049 条物理记录、83 个合法空日、4,039,070 条 rec_time NULL、15 条缺 URL；最大单日 69,498 条、35 页。数字为历史审计时点，不是当前 Prod 恒定存量或 Tushare 全市场完整性承诺。

### 2.1 2026-10-04 真实核验

| 请求/来源 | 结果与含义 |
|---|---|
| ann_date=20260930，limit=3，不传 fields | 返回三行、五个默认字段，不含 rec_time |
| 同日显式五字段 | 返回三行，字段与默认一致 |
| 显式六字段，155162.SH / 20230609 | 两行均 rec_time NULL，一行 URL NULL、一行有 URL；两行必须保留，且不能按股票池过滤 |
| 无业务时间参数，limit=3 | 返回三行，样本 ann_date=20261001；受限样本不证明无日期可完整拉历史 |
| 只传 000001.SZ，limit=3 | 返回不同公告日三行，证明代码参数是过滤而非日分区事实 |
| 20260930 闭区间，offset=2000，limit=2000 | 返回 257 行、六字段 |
| 同日 offset=0 / 2257，limit=2000 | 分别 2,000 行 / 0 行；不能遇满页即结束 |
| Prod 已知 id=20080447..20080451，只读六字段中的时间投影 | 原始 ann_date 是 20260726，原始 rec_time 无时区；类型列已转 DATE/TIMESTAMPTZ。一条发布时间为次日，不能按 rec_time 分区 |

MCP 空结果为 JSON 空数组，不能证明 SDK 的空 DataFrame 具有六字段；SDK 合法空页与异常无 schema 必须隔离测试及最小真实核验。调用只做查询，没有写 Prod 或 Lake。

## 3. 硬约束

| 编号 | 必须遵守的口径 |
|---|---|
| R01 | Raw 物理字段只有 ann_date、ts_code、name、title、url、rec_time，顺序固定 |
| R02 | 保留源字符串、NULL、空字符串、空白；不改名、不 trim、不转时区、不补值；SDK 的 pandas NaN 还原为源 NULL，真实数值仍报类型错误 |
| R03 | 只去除六字段完全相同记录，NULL 与空字符串不同；不按代码/日期/标题或 URL 合并元数据 |
| R04 | 自然日分区，不用交易日、股票池、活跃名单或上市状态过滤 |
| R05 | Prod 仅历史只读；日常直接 Tushare；没有 Prod fallback 或 Prod Ops 状态依赖 |
| R06 | 缺 URL、rec_time 合法；空日可完成。字段结构/类型/分区异常阻断候选，不静默删除记录 |
| R07 | 每页持久化；Python 内存仅与单批有关；不得全历史 DataFrame 或 fetchall |
| R08 | 独立 staging、完整候选校验、逐文件原子提升、checkpoint、取消与物理续跑；禁止 Kopia |
| R09 | 日常七日合并重拉；首次补齐 2026-10-01 至启用前一天；停机缺口单独补齐 |
| R10 | 原始业务文件提交不依赖事件写入成功；事件失败必须可补报，不重新覆盖业务文件 |
| R11 | 仅 Raw；正式写湖、runless 事件及启用调度按阶段另获执行授权 |
| R12 | 不新增正式状态数据库/摘要资产；运行 checkpoint 只用于执行，不作为数据事实或 freshness 来源 |

## 4. 数据集与文件

名称：上市公司公告；asset key：`raw_tushare_anns_d`；来源：Tushare；层级：Raw；分区：从 2020-01-01 开始的专属自然日 DailyPartitionsDefinition，时区 Asia/Shanghai，不依赖交易日动态分区。

正式文件：

```text
/Volumes/datasource/data_lake/raw/tushare/anns_d/ann_date=<YYYY-MM-DD>/part-000.parquet
```

候选、分页文件、DuckDB spill、checkpoint：

```text
/Volumes/datasource/data_lake_staging/anns_d/run_id=<run_id>/...
```

六字段均为 nullable STRING/VARCHAR；ann_date 保存源 YYYYMMDD 字符串，目录采用 ISO 日期。schema 核验使用 hive_partitioning=false，避免目录虚拟字段覆盖物理字段。

缺日期、不可解析日期或源日期不属于请求 unit 时，不丢弃该行：整个候选失败，保留分页文件与样本，修订原因后重跑。历史已审计范围没有缺日期，不能据此省略反例测试。

合法空日写带完整六字段 schema 的零行文件。每日 materialization 表示一次完整分页及合并成功，不表示公告数必须大于零或源端永久完整。

## 5. Bootstrap 与日常运行

### 5.1 Bootstrap

读取按自然月有界 unit，写出仍按自然日。一月一个只读连接/快照，服务端游标按 ann_date、id 排序（P0 已测；设置 cursor_tuple_fraction=1.0），fetchmany=10,000；id 仅辅助 staging/checkpoint，不能进入 Raw。共 81 个源 unit，避免 2,465 次逐日建连接。

在服务器端只投影 raw_payload 中的六个业务值，禁止回传完整 raw_payload；不导出 api_name、fetched_at、row_key_hash 等系统字段。不重算 Prod hash，不修改 Prod 表、索引或同步规则。具体 SQL 与空值/JSON 类型检查见 LLD。

一月分页文件完成并校验后，DuckDB 向量化生成每日候选。全部月候选完成检查后逐日提升；失败月份重新读取，已提升文件根据 checkpoint 与实际 checksum 续跑。全历史不保持一笔事务；也不宣称跨月源快照一致。

文件生成与 runless 事件补录分开。正式 check 未通过的文件不得补绿色事件。

### 5.2 日常与补拉

定时 schedule 每天 08:00，Asia/Shanghai，默认 STOPPED。运行日 D 提交 D-7 至 D-1 七个日期 run，按日独立提交；run key 含调度日期和目标日期，次日可重新更新同一分区。

每页 limit=2,000，实际返回行数推进 offset，短页结束，满页继续；分页顺序变动存在源接口固有限制，七日回看降低风险但不能消除风险。

每个日候选：已有六字段记录 UNION 新页六字段记录，再按全字段 DISTINCT。已有文件读取一次，写出全量日候选后原子替换。重放结果集合相同，不要求 Parquet 二进制字节相同。

同日并发写必须排他，提升前核验正式文件指纹仍等于构建时的基线；否则停止并重建，避免丢更新。取消不领取下一页或下一日；已提交日保留。

## 6. 性能预算与开发前门禁

| 项目 | 证据/设计预算 | 超预算处理 |
|---|---|---|
| 历史范围 | 81 月、2,465 日；审计物理行 12,064,049 | 当前 plan 刷新精确行数/日期集，不把历史数字作为固定验收值 |
| Prod 读取 | 81 个主读取连接/事务；fetch 10,000；全范围约 1,207 个等效满批，月边界和 EOF 有额外 fetch；另计 plan/audit 查询 | 月 unit 上限 200 万行，SQL timeout 60 秒，月读取 30 分钟；超出停止，不缩减数据 |
| 日常 Tushare | page=2,000；已知最大日 35 页；默认请求结束后间隔 5 秒；单日最多 100 次请求（含重试），最多三次尝试/页 | 停止该日且不提升截断文件；不绕限流或无限重试 |
| 七日窗口 | 最大已知日规模重复七次约 245 页；窗口请求预算 350、时间预算 60 分钟 | 调度共享 tick 配额后超过即停止派发，未完成日期手工补拉；不伪造完成 |
| 内存 | Python 单 fetch 批次/单源页；DuckDB 每连接 2GB、2线程、spill 20GB；进程 RSS 目标≤3GB | 最小样本实测；达到硬预算失败保留候选 |
| 文件数量 | 一日一个正式文件，初始 2,465 个含空日；候选与临时 part 数另计 | 不为小文件强制改月分区；测真实日期/代码查询耗时 |
| 磁盘与耗时 | P0 单批已测：10,000 行 Parquet 211,661 字节、RSS 129,892,352 字节；完整月吞吐待 P3；Prod 表大小不能替代 Lake 估算 | P0 用样本得到压缩率及吞吐，按候选+正式+spill+reserve计算空间；P0 基础预算已闭合，可进入P1；全量执行仍需样本实测与独立批准 |

本表给出默认执行上限，不是已达到的性能结果。bootstrap 总时长必须按样本月吞吐外推并记录误差；Tushare 七日最坏已知页规模，仅五秒等待约 20 分钟，另加 API、重试和文件计算。日常预算共享不能只放在独立七个进程内。

P0 只读测量用日期索引聚合、EXPLAIN 及有限六字段样本；临时 Parquet 基准只在 /private/tmp，不能凭设计授权写移动盘。月 SQL/游标超时语义须真实验证，不能把 statement_timeout 当整月总时限。

## 7. 检查、观测与验收

两个阻断 check：文件合同（路径、物理 schema、日期一致、全字段重复）与交付对账（完整分页、行数等式、现有行保留、目标读回、文件指纹）。checks 读取文件与可验证运行交付证据，不再请求 Tushare，不读 Prod Ops。check 分区必须和 asset 分区一致，事件必须带 partition。

不建立永久第三份状态表。Dagster event 保存本轮计数/源页数/末页/文件摘要，文件为存量事实；staging checkpoint 保存执行恢复证据。已有 event 不能替代物理文件检查，历史 event 也不能证明当前文件未改变。

每页/每文件进度更新，最长 30 秒可见更新：阶段、日期/月、已读、页数、已完成日、总日数、最后更新时间；不知道源总行数时不虚报百分比。心跳与业务进度分开，ETA 不可靠则显示暂无法估算。

最小真实验收覆盖合法空日、缺 URL/rec_time、满页日、同标题不同源版本、运行—取消—续跑—物理读回、相同范围重放零新增，以及事件写入失败后的补报。正式资源写入另获阶段批准。

## 8. 实施阶段

| 阶段 | 输出与退出条件 |
|---|---|
| P0 契约与预算闭合 | 固定六字段、Prod 查询执行计划/源类型/空间/吞吐测量、配置审计；未测指标不得写已完成 |
| P1 核心实现 | contract/path/source/streaming writer/checkpoint/checks，隔离正反测试及真实只读验收 |
| P2 DG 接线 | asset/catalog/schema/partition/job/schedule/checks；正式调度保持停止；defs 验证 |
| P3 Bootstrap | plan→批准样本→读回→批准全量候选/提升→汇总对账；不补事件冒充文件完成 |
| P4 状态与日常验收 | 分开批准 runless 补录、衔接区间补拉、日更新取消续跑与调度启用；最终审计 |

设计轮只交付方案与 LLD，没有代码或生产执行。随后P0预算核验已完成（§10）；下一步P1开发，正式执行仍按阶段授权。所有批准的口径变更必须同步本文件和 LLD。

## 9. 影响面与后续工作

已使用 CodeGraph query/impact 核对 TushareResource、daily_basic_history_query、Prod AnnsDDAO，并补读 source/ledger/files、catalog、resources、paths、通用分页实现和测试。共享 TushareResource 有其它消费者，本专项优先新增公告专用有界 adapter，不顺手修改公共调用行为。

DG 不 import Prod src/ops 或 src/app，不挂入生产 Web。未来下载器切 DG、SQLite 台账查询能力、名称/代码/拼音检索、前端设计另有专项合同；本方案不提前承诺其实现方式。静态图不能证明正式 definitions 加载成功，动态验证在 P2 完成。

## 10. P0 结论（2026-10-04）

[验收报告](../../reports/anns_d_dg_p0_20261004.md)及[聚合/计划证据](../../reports/anns_d_dg_p0_20261004.json)记录实测与估算。P0通过，仅开放P1开发，不授权正式文件/事件/调度执行。

修正两项执行细节：月读取稳定排序改为ann_date、id，设置cursor_tuple_fraction=1.0；SDK的pandas NaN还原为源NULL，不能把任意float转NULL。六字段原始业务含义不变。

当前存量仍12,064,049行；81月最大543,563行；按现存记录推算最大七日154次请求、含月EOF约1,330次fetch。10,000行六字段样本集合差0，合法空日SDK六字段齐全。历史初始化规划15–60分钟、磁盘保守预留35GiB，仅作可行性预算；完整传输、月RSS和写盘耗时必须在P3样本验收，不能据线性外推宣称全量已通过。
