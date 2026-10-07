# 上市公司公告 PDF 本地归档技术方案 v1

更新时间：2026-10-08。状态：Q1—Q4已完成，本机PG迁移、统一启用和获准旧文件清理见网页LLD §26及[收尾报告](../../reports/wealth_data_center_q4_cleanup_acceptance_20261008.md)。Q3隔离验收见[数据中心 LLD §25](../../wealth/docs/pages/data-center/data-center-announcements-low-level-design-v1.md)及[报告](../../reports/wealth_data_center_q3_acceptance_20261007.md)。当前开发版执行口径见本文 §14；§1—§13 为此前 DG/SQLite/DC 阶段的历史记录，原 SQLite 存储、运行时升级及“不依赖 PG”的说明已被 Q3 替代。文件、来源、限流和恢复协议继续有效。本机已启用Q4版本；DG日常稳定性及全历史数据质量继续独立验收。

§1—§12保留此前DG读者、五URL真实归档、台账维护及网页设计阶段的记录；M0—M3为Prod版本历史。原方案提交777d6901、下载器提交9f8faacf，独立旧验收台账曾升级到2；这些历史证据不证明此次schema3或网页已在正式环境执行。

## 1. 目标、依据与范围

将现有本地公告下载器的元数据来源迁移到 DG 已发布的 Raw Parquet。继续按公告日期、完整代码建目录，以标题命名，支持日期闭区间、可配置请求间隔、外盘门禁和文件任务级续跑。迁移后无需连接 Prod、PostgreSQL、ClickHouse 或 Dagster 服务，也不调用 Tushare。

依据为用户确认的本机运行方式、DG Raw 只保留源业务元数据的决策，以及本轮先完成下载器消费方案的授权：

- [DG 公告接入方案](../../lake_console/docs/design/dagster-anns-d-onboarding-plan-v1.md)及[DG LLD](../../lake_console/docs/design/dagster-anns-d-onboarding-low-level-design-v1.md)。
- [六字段合同](../../lake_console/orchestrator/src/orchestrator/defs/anns_d_contract.py)、[正式路径](../../lake_console/orchestrator/src/orchestrator/defs/paths.py)、[原子提升实现](../../lake_console/orchestrator/src/orchestrator/defs/anns_d_io.py)。
- 当前 [CLI](../../src/scripts/download_announcements.py)、[DG reader](../../src/foundation/clients/announcement_archive/source.py)、[账本](../../src/foundation/dao/announcement_archive/ledger.py)、[文件恢复](../../src/foundation/clients/announcement_archive/files.py)。
- [子系统边界](../architecture/subsystem-boundary-plan.md)、[DG 性能治理](../../lake_console/docs/design/dagster-data-pipeline-performance-governance.md)、Tushare doc_id=176 的[本地接口说明](../sources/tushare/大模型语料/0176_上市公司全量公告.md)。

本轮已替换现有工具的 source 与枚举流程，同步迁移台账接口和测试；不保留 Prod/DG 双读取模式或缺文件回落 Prod。SQLite 延续下载台账职责，不新增公告业务数据库、搜索索引、调度或页面。不改 DG 数据集合同、同步规则、DatasetDefinition、Ops TaskRun 或正式 Lake 文件。

DG 日常更新还需连续运行验收。按用户本轮决定，下载器设计、隔离开发及已验收历史文件的只读验证可并行推进；这不把 DG 日常验收标为完成，也不授权全历史下载。数据中心与股票名称/代码/首字母搜索继续留在后续阶段。

## 2. 当前事实及证据边界

| 项目 | 当前事实与迁移要求 |
| --- | --- |
| 当前下载器 | DG 正式 Raw 按日固定 fd、每批 500；完整枚举并校验封存后按本轮文件集合下载；无 Prod 连接或逐文件源查询 |
| DG 正式文件 | `/Volumes/datasource/data_lake/raw/tushare/anns_d/ann_date=YYYY-MM-DD/part-000.parquet`，自然日分区 |
| Raw 物理字段 | 依次为 ann_date、ts_code、name、title、url、rec_time，均为可空字符串；没有 id、row_key_hash 或 group_key |
| 两种日期表示 | Raw ann_date 是 YYYYMMDD；分区与归档目录是 YYYY-MM-DD。只在下载投影中转换，不改 Raw 值 |
| 数据保存规则 | 六字段完全一致才算重复；NULL、空串、空白不同。不同源记录均保留，PDF 可按既有文件身份复用 |
| 发布与读取 | DG 按日 os.replace 原子替换。消费者固定单日文件句柄读取，不持有 DG 写锁、不访问 staging |
| 历史证据 | DG 方案 §15、§19 的历史与衔接验收合计 2,469 文件、12,064,773 行、86 空日，覆盖 2020-01-01 至 2026-10-04；不是本轮重新全量审计 |
| 运行依赖 | 根项目已声明 local-lake DuckDB 可选依赖；本机现有根环境 DuckDB 1.5.5 可用，未安装依赖 |

2026-10-05 临时目录实验：先打开旧 Parquet，再原子替换路径，DuckDB 通过 `/dev/fd/<fd>` 仍读到旧内容，按路径重开读到新内容。只证明本机这一读取机制可行；不替代源实现、内存、取消、真实拔盘或 DG 下载验收。

## 3. 必须满足的开发约束

| 编号 | 口径 |
| --- | --- |
| R1 | 沿用本地 CLI 和默认归档根 `/Volumes/datasource/announcements`；迁移后只读 DG，不连 Prod、不依赖 DG 进程运行 |
| R2 | start/end 必填 ISO 日期，按 ann_date 闭区间逐自然日枚举；不按交易日、股票池、上市状态过滤 |
| R3 | 归档路径为 YYYY-MM-DD/完整 ts_code/标题.pdf；Raw 八位日期转换必须与旧 artifact_key 一致 |
| R4 | 标题清洗、防同名覆盖及已有路径分配规则不变；元数据六字段完整保留，不合并不同源记录 |
| R5 | interval 默认 5 秒，可显式 0 调试；首次、重试、重定向都服从同一限速器及持久冷却 |
| R6 | PDF prepared/原子提交/哈希恢复协议不变；保留已有台账与文件，缺失或损坏文件允许重新下载 |
| R7 | 验证外盘后才创建归档、读取 Raw、打开账本和请求 PDF；来源卷与输出卷分别核验，禁止写 Lake/staging |
| R8 | 每次启动新枚举，纳入新记录；源记录身份与文件身份分离，旧 Prod PDF 可跨来源复用 |
| R9 | 每日固定一个文件版本；整个范围不是全局快照。范围全部枚举并校验封存前零 HTTP；缺文件不能当空日 |
| R10 | 每批最多 500 行，单日单次顺序扫描，不做 OFFSET 重扫、全范围 fetchall 或每 PDF 的 Parquet 存在性查询 |
| R11 | 逐批持久化、日级输入指纹、显式终态和可取消读取；台账 schema 升级原子完成，失败不能损伤旧账本/PDF |

## 4. 使用方式及配置边界

以下命令已切换到 DG，执行会写归档并可能请求真实 PDF。2026-10-05 已在独立目录完成五 URL 验收；默认目录中的其他批次未执行。大范围下载仍需指定日期、间隔和预算：

```bash
.venv/bin/python -m src.scripts.download_announcements \
  --start-date 2026-07-26 \
  --end-date 2026-07-26 \
  --interval-seconds 5 \
  --output-root /Volumes/datasource/announcements
```

四个参数、日期语法、默认间隔与输出根保持原样。元数据来源切换是本方案明确的入口行为变更；已一次迁移 CLI、source、ledger 和测试，不新增 source/backend/lake-root 参数，不保留隐式 fallback。

来源固定为 DG 正式根，由一个 source 工厂消费；不读取旧 lake_console/config.local.toml，不加载 DATABASE_URL/GOLDENSHARE_ENV_FILE，不要求启动 PG/CH/SSH/DG。源文件不存在时提示缺失日期并阻断，下载器不代替 DG 同步。完整配置审计见 LLD §2。

## 5. 源读取与一致性

按照日期闭区间逐日读取唯一正式文件，拒绝符号链接、非普通文件、错误六字段 schema 和分区不符。合法零行 Parquet 表示空日；文件缺失、损坏或无法核验表示缺口/错误，不能跳过后宣称完成。

每次只固定一个日期文件的 fd，读取全部六字段；DuckDB 设置 hive_partitioning=false，防止目录虚拟字段覆盖 Raw ann_date。读取过程中路径被 DG 原子替换，继续读取已打开版本，下一次命令才纳入新版。打开文件前后与批次边界核验来源卷；同一已打开文件被原地修改则阻断。记录该版本的大小、SHA-256、行数与日期，并关闭本日 DuckDB 连接及句柄，再进入下一日，避免复用 fd 编号时沿用上日文件缓存。

所有源记录和本轮文件集合均成功枚举、日校验完成后才封存运行输入，开始 HTTP 下载。封存描述的是各日实际读到的版本，不声称跨日同一时点快照、不证明 Tushare 永久全量、不替代 DG blocking checks。下载阶段使用封存文件集合，取消原来的逐文件 Prod has_artifact 查询，也不能用每文件扫描 Parquet 替代它。

## 6. 身份、台账与恢复

源记录身份由六个原始值的固定序列化 SHA-256 生成，区分 NULL、空串和空白。源 scope 带 DG 来源卷 UUID、卷内正式数据集路径及合同版本，不能借用 Prod hash/id。

文件身份继续使用原算法：ISO ann_date、原 ts_code、去首尾空白后的 URL。例如 Raw `20260726` 转换为 `2026-07-26` 后，同代码/URL 的文件 key 必须与 Prod 版本相同。name/title/rec_time 的差异产生不同来源映射，但不重复请求同一文件；已有路径及首次标题保留，不因新枚举顺序改名。

缺 URL 行保留六字段映射并计数，不发 HTTP；NULL rec_time 不阻碍下载。非法非空 URL、缺标题/非法代码按现有文件失败口径保留元数据，不静默丢行。此规则不修改 Raw。

账本继续位于本机 Application Support，以输出卷 UUID 和卷内归档目录派生身份。schema 1→2 用显式事务迁移，保留旧来源记录、文件状态/路径/size/hash、请求冷却及历史运行。新 DG 来源与旧 Prod 来源分别追溯，共用 artifacts。不得清空账本、改归档身份或自动备份/删除 PDF。具体字段与迁移见 LLD §5。

续跑仍是文件任务级：新命令重枚举选定范围，复用有效已完成文件。未完成枚举保留诊断事实，但不从旧行序号继续读取被替换文件。删除成功 PDF 后下次运行重新下载；prepared 恢复和损坏文件保留重下规则不变。不实现 HTTP Range。

## 7. 外盘、限流与文件协议

输出门禁、标题预算、串行请求、全局间隔、Retry-After、403/验证码停止、512 MiB 单文件上限、64 KiB 分块、prepared/fsync/os.replace/成功落账协议继续沿用，见 LLD §3、§6、§7。源读取仅只读，不在 Raw 或 staging 创建探针、锁、缓存、临时文件或 DuckDB spill。

来源默认为 datasource；输出根可在另一已验证外卷。不能因输出卷可写就推断来源卷有效，或因来源存在就跳过输出门禁。读取/下载任一所需卷失效都停止领取新任务，保留已提交 PDF，禁止回落系统盘。

## 8. 成本、进度与性能门禁

枚举工作量为选定日期文件的总字节/总行数，不是 PDF 请求次数。逐日最多两次流式指纹读取加一次 Parquet 顺序扫描，不按 PDF 次数重复读源。枚举 SQLite 事务数为 `B=Σceil(日行数/500)`；按已有历史+衔接证据推算约 24,130—26,598 批，这是单批内存限制下的本机落账批次，不能套用旧存量清洗 apply 的批次数。

DuckDB 单连接内存预算设计为 256 MiB、1 线程、禁止 spill/自动扩展；Python 只持有一批元数据和一个传输块。256 MiB 是引擎限制，不是进程 RSS 保证。每个阻塞 DuckDB 读取调用预算 15 秒，超时中断并阻断，不自动加内存/超时或创建 spill。SQLite 维持逐批短事务及增量计数，不能每次进度扫描全任务。

实施验收必须用已有最大日量级（历史最大单日 69,498 条）、合法空日及窄范围测量：读取/落账耗时、峰值 RSS、台账每行空间、事务次数、取消延迟及零外部数据库连接。先给出所选范围的枚举耗时/账本空间/PDF 容量预算，再执行范围下载；现有台账会保存逐条来源映射，不能把它的空间成本遗漏。全历史成本暂未测量，不承诺完成时间。

PDF 粗略耗时仍为 `N×平均传输耗时 + max(N+额外请求数-1,0)×间隔 + 额外退避`；5 秒间隔下 10,000 请求仅等待约 13.9 小时。Raw 行数不等于唯一 PDF 数，不能据 1,206 万行宣称同等请求数。

进度每 ≤5 秒显示阶段、当前日期、完成日数/总日数、读取行数、来源映射量和文件任务数；下载后显示完成量/总量、成功/跳过/失败、冷却与更新时间。未知总行数或 ETA 明示未知，不用心跳代替业务计数。

### 2026-10-05 实施及只读证据

[验收报告](../../reports/anns_d_download_dg_reader_acceptance_20261005.md)及[数量/指纹/性能](../../reports/anns_d_download_dg_reader_acceptance_20261005.json)：四个正式日期读回 76,685 条，最大存量日 2024-04-26 为 69,138 条、139 批、约 39.077 秒；原 69,498 是历史同步源输入峰值量级，不是该文件物理条数。RSS 峰值 128.78 MiB，零 PDF 请求，临时台账约 1158.16 字节/行。上述只读阶段没有升级正式台账或下载 PDF，其秒数不包含实际 CLI 的输出卷检查与网络成本。后续五 URL 真实阶段已验证独立旧台账升级与文件复用，见下文；现场拔盘仍未验证。

### 2026-10-05 五 URL 真实归档证据

[真实验收报告](../../reports/anns_d_download_dg_pdf_acceptance_20261005.md)及[机器可读证据](../../reports/anns_d_download_dg_pdf_acceptance_20261005.json)：DG 2026-07-26 完整自然日五条/五 URL，独立旧归档 schema 1→2、五份零请求复用；新归档首份后 SIGINT 得到 130/cancelled，再执行只下载剩余四份，第三次全部跳过。GET 共五次、均 200，最短结束至下一开始间隔 5.119 秒；新五份共 925,599 字节，旧新十次 size/hash 读回匹配台账。默认归档另有九月批次，本轮未升级该台账或领取这些任务。删除后重下仍仅有隔离测试证据，不删除现场 PDF；现场拔盘、全量运行与 DG 连续日常验证仍待后续。

## 9. 接下来的实施顺序

| 步骤 | 本阶段完成条件 |
| --- | --- |
| 1 方案与 LLD | 已完成并提交 777d6901；源合同、逐日读取、身份、配置、台账迁移和验收映射明确 |
| 2 迁移实现 | 已完成并提交 9f8faacf；替换 Prod reader/枚举链，schema 2 原子升级，全部测试消费者迁移；清零运行期 DB/id/has_artifact 依赖；独立旧验收台账真实升级通过，默认台账尚未升级 |
| 3 隔离与只读验收 | 已完成；正反例/退出/取消/续跑与架构回归通过，四个正式日文件 76,685 条对账通过；不写正式 Lake、不下载 |
| 4 DG 最小真实下载 | 本轮授权范围通过：五个唯一 URL，旧 PDF 零请求复用、取消—续跑—零请求重放—size/hash 对账；删除后重下只在隔离测试验证，真实删除需明确授权，现场拔盘未做 |
| 5 台账查询与维护 | 已完成本地六子命令 CLI、隔离回归和正式只读验收；边界与证据见 LLD §16。本阶段不下载 PDF、不批量重置、不修改历史运行结果 |
| 6 数据中心 | 原台账阶段在此停下；2026-10-06 产品/Figma R1已确认并获准编写网页技术文档，见下文§12。网页/API尚未开发，实施需分期授权 |

DG 日常稳定性验收继续独立进行；下载器只读验证可使用已验收的历史文件。任何大范围执行仍需指定日期/间隔并完成容量与运行预算，不从本方案完成自动获得授权。

详细实现点、配置与测试门禁见 [LLD](anns-d-pdf-download-low-level-design-v1.md)。

## 附录：Prod 版本历史证据（不作为 DG 迁移执行口径）

原 M0 设计提交 45c19af3；M1/M2 完成，M3 在 2026-10-03 对五个真实 URL 完成下载、取消、续跑及零请求重放，保留十份验收文件。详见 LLD §11—§13 和[真实验收报告](../../reports/anns_d_pdf_m3_acceptance_20261003.json)。这些报告与文件保留，DG 迁移不得将它们冒充为新来源验收。

以下保留原日期记录。旧分组覆盖、旧 id 删除与“只保留被覆盖版本”已被完整六字段 Raw 保存规则替代；旧逐文件数据库复核仅描述当前尚未迁移的 Prod 实现，迁移后由本方案 §5 的封存输入替代。段落中的“下一阶段”“本轮”“待验证”只表示记录当时状态。

### 2026-10-02 旧分组方案与 Prod 消费者记录（已被替代）

元数据同步仍由既有anns_d主链负责。2026-10-02用户确定Raw物理只留不被覆盖版本，下载枚举继续显式读取Raw id和row_key_hash，无需is_current过滤。上界id只是本轮枚举边界，不是永久公告身份；每次新轮次从0重枚举。被完整记录替代的旧id可以被删除，新版获得新id；元数据内容指纹可能变化，文件身份仍是日期、代码、URL。

URL NULL/空值：保存该行的本地来源映射，记录skipped_missing_url，并推进同批游标；不创建空URL下载身份、不发HTTP、不让NULL.strip()中断批次。非空但非法URL按既有invalid_url文件失败口径，不丢公告元数据。rec_time为NULL只影响元数据展示，不影响文件任务。

本地source_records.artifact_key在无URL情况下需要允许NULL/无关联；后续新有效URL版本可创建文件任务。新一轮不纳入已经物理删除的冗余记录及其新下载任务，不删除旧轮次已经验证成功的文件。每次领取文件前按日期、代码、URL复核至少一个对应公告仍存在，不能只凭旧id存在与否判断同一URL文件是否需要，避免枚举后被覆盖继续下载；查询需短只读有界，不自动删除账本映射。跨轮次成功文件按既有日期/代码/URL身份复用。

适配验证：物理替代后的旧来源映射不错误领取、缺URL映射/统计/游标同事务、缺时间可下载、代表换ID相同URL不重复下载、旧轮次未完成文件的有效性复核、非完整性快照边界。现行M1没有上述NULL与覆盖适配，不能在新公告合同部署后直接当作已兼容运行。


### 2026-10-02 Prod 消费者适配记录

无 URL 的公告写入本地 source_records，artifact_key 为 NULL，不领取 HTTP 请求；游标与 missing_url_count 同一 SQLite 事务提交，输出 skipped_missing_url。已有账本通过显式 ADD COLUMN 补 run 计数，不清空记录。

文件身份仍为日期/代码/URL；领取前以短只读事务查询该文件身份是否仍存在，不能用可能被删除的 raw id 当永久身份。若已无该文件身份，标记 skipped、reason=source_record_replaced；新版保留同 URL 时仍可复用已完成文件。新轮次重新枚举，当前轮次冻结的 upper_id 不保证发现随后新增版本；已有 PDF 不删除。每文件复查查询使用 ts_code/ann_date 现有索引，Prod 代表性性能待 M3 验证。

P1 回归包含缺 URL 不请求、游标提交/回滚、被替代来源不请求；已有成功文件恢复和身份测试继续通过。未进行真实 HTTP 下载或写入正式外盘。


2026-10-03 M2交付：files.py修正NULL代码/标题未处理异常和已完成文件多硬链接恢复门禁，遵守原失败/阻断规则；无新增参数或业务合同。专项及架构回归88项通过，未写Prod或正式外盘、未请求真实PDF。下一阶段仍为M3最多5个URL的外盘验收，详见[LLD§12](/Users/congming/github/goldenshare/docs/datasets/anns-d-pdf-download-low-level-design-v1.md)。


2026-10-03 M3交付：真实外盘5个源URL的下载、SIGINT取消、续跑和零请求重放均通过；管道进度缓冲已修复，89项回归通过。首次未有效中断的成果保留，独立复测目录保留5份，合计10份物理验收文件。未写Prod、未下载全历史。范围执行仍等待管理员指定日期和间隔，真实拔盘及其他URL域名未验证。详细记录见[LLD§13](/Users/congming/github/goldenshare/docs/datasets/anns-d-pdf-download-low-level-design-v1.md)。

## 11. 台账查询与维护阶段边界（2026-10-05）

用户明确要求完成台账查询和维护能力后停下，数据中心页面尚缺 Figma 及产品功能细节讨论。新增独立 `python -m src.scripts.announcement_ledger` 入口，保留原下载 CLI 四参数和行为；不开发数据中心页面/API、股票搜索产品合同或 Figma。详细命令、配置审计、代码点和测试映射见 LLD §16。

查询支持归档概况、运行历史、按日期/代码/标题/状态筛选文件、单文件及其来源映射；只读打开 schema 1/2 台账，不创建/升级台账或探测写文件。单文件 verify 只读核验物理大小/哈希；repair 按明确 artifact_key 获取既有归档排他锁，复用原 Files.allocate/recover，恢复 prepared 或将缺失/损坏/失败文件整理为可重下状态。保留损坏/未知文件、来源映射、尝试次数、冷却及历史运行结果。repair 不请求 URL，重下载由用户另行执行原日期下载命令；不提供强制覆盖、清空台账、删除 PDF、批量 reset 或配置 URL 的能力。

所有列表有界分页，复杂查询有超时/Ctrl+C；查询不得把台账状态 succeeded 冒充为现场文件已经核验。正式归档只做有限只读验收；维护写入、丢失/损坏/中断故障在临时隔离归档验证，不在现场删除 PDF。DG/Prod/Lake 同步与全量下载不在本阶段授权内。

本阶段已完成：新增独立台账 CLI 六子命令，schema 1/2 完全只读观察、单文件核验与排他修复；所有列表采用有界游标，读取快照总预算 4 秒，在文件哈希/卷复检前关闭以减少对 SQLite 写入的影响。默认旧台账与独立新版台账实际共 16 次只读命令、六文件核验通过，两份台账前后哈希一致；修复与缺失/损坏/取消等路径仅在隔离目录执行。详细配置、代码/测试映射、命令及[验收证据](../../reports/anns_d_ledger_maintenance_acceptance_20261005.md)见 LLD §16。没有开发数据中心页面/API/Figma；按用户停止线停下，后续先完成产品细节和 Figma 再另行授权。

## 12. 数据中心产品化目标（2026-10-06；未实现）

上述停止线是2026-10-05台账阶段的历史边界。产品/Figma R1已确认，用户现授权编写[网页技术方案](../../wealth/docs/pages/data-center/data-center-announcements-implementation-design-v1.md)和[网页LLD](../../wealth/docs/pages/data-center/data-center-announcements-low-level-design-v1.md)。它们负责页面/API、本地查询投影、原run继续、关联失败批次与业务进度目标，本文与原LLD保留当前CLI及已有验收基线。

目标变更包括：共享下载主实现由scripts迁到Foundation基础能力、执行控制归Ops并由App装配；台账schema3保留旧身份/路径/结果/冷却，全部消费者同轮迁移；新增可重建日期索引，仍只读DG六字段Raw。身份算法、文件提升协议、CLI现有参数/输出/退出行为不变。GUI固定归档根、仅日期创建，原任务继续/精确失败重试不能用整段CLI重跑替代。

本轮只写设计，不迁移正式台账/索引、不调用PDF或DG/Prod。网页方案中的schema3/新API/运行控制均未落代码，不把原M0—M3与台账CLI验收升级成网页交付；后续DC0—DC5分期门禁见网页LLD。

## 13. DC1共用核心和schema3（2026-10-06）

用户已确认DC1与本地pypinyin依赖。共享核心现位于Foundation clients/announcement_archive，台账/查询在DAO，执行与单文件修复归Ops；两个原CLI为薄入口。写入口单事务升级schema1/2→3，只读不升级；旧身份/路径/来源/结果/冷却保留。旧主实现包及import清零。§1—§12保留此前阶段口径，当前实现以网页LLD§14和[验收报告](../../reports/wealth_data_center_dc1_acceptance_20261006.md)为准。

完整387项通过，职责收敛后受影响217项复测通过；正式Raw五条只读指纹对账通过。正式台账未迁移，没有远程PDF/DG/Prod/Lake写入。schema3基础不代表预览/继续/精确重试/API/页面已完成；下一步DC2查询后端另按阶段推进。


## 14. Q3 统一 PG 的执行口径（2026-10-07）

下载 CLI、台账维护 CLI 和 Web 共用 `announcement_archive` PG 存储，业务公告仍直接读取 DG Raw。PG 仅保存实际下载来源映射、文件事实、任务、冷却和必要查询控制，不另建全市场公告元数据副本。完整合同以[数据中心 LLD §22](../../wealth/docs/pages/data-center/data-center-announcements-low-level-design-v1.md)为准。

1. 配置只读取 `ANNOUNCEMENT_ARCHIVE_DATABASE_URL`，默认空，支持既有 `GOLDENSHARE_ENV_FILE`；不使用主 `DATABASE_URL`，不新增 DSN 命令行参数。正式连接固定本机5432、`goldenshare_lake_meta`，独立连接池最多4连接；Web 查询和下载共享这一池。
2. 输出卷与 DG 来源验证通过后才访问 PG。运行时只能校验已显式安装的 schema；没有自动建表或 SQLite 升级。首次下载可初始化已验证输出卷对应的新 archive，所有读写按卷 UUID+卷内相对目录派生的 `archive_id` 隔离。
3. 日期闭区间、请求间隔、目录、标题命名、跳过有效成功文件、缺失/损坏重下、HTTP限速与prepared恢复规则不变。枚举每批最多500，读写采用短事务；封存前不下载，Web继续/失败重试只处理原冻结集合。
4. 文件提交、业务结果与进度观测分别提交。停止/owner最多每0.5秒检查；进度和心跳默认5秒，失败也按此频率节流，不为每个64KiB块查询PG。每次HTTP（含跳转和来源探测）前必须成功提交 `request_in_flight`；PG不可写时不发新请求，不自动恢复HTTP。
5. 原CLI参数和退出码保持。JSON的 `ledger_path` 和顶层 `schema_version` 移除，改为真实 `storage`：`kind/database/schema/archiveId/schemaVersion`。分页参数 `before-rowid/after-rowid` 仍为正整数，实际按PG `row_seq`读取。
6. SQLite只在显式迁移的只读旧源校验中保留，运行时消费者清零。Q3未迁移/删除正式SQLite、PDF或Raw，未改本机env、未安装/卸载软件。正式迁移和统一启用见Q4；DG日常稳定性验收仍独立。


Q4正式启用记录（2026-10-07）：Q3提交b4c590fd后，已迁移4份旧台账并逐批完整值重放/读回，启用本地PG及恢复Web8000。旧SQLite文件保留，清理必须经独立批准的--cleanup-plan/--cleanup运营流程；不再是运行期后端。[Q4报告](../../reports/wealth_data_center_q4_acceptance_20261007.md)记录378份PDF物理核验、默认363份查询和独立5文件复用，网页LLD§26保存实际配置与未完成边界。

2026-10-08 Q4完成：按用户明确授权提交代码fa08d45d并执行7文件精确清理；PG台账独立可查、378份PDF物理摘要匹配，正式Raw及共享库保留。旧源不再存在，正常启动不迁移、不回退SQLite；[收尾报告](../../reports/wealth_data_center_q4_cleanup_acceptance_20261008.md)和网页LLD§26.4为最新状态。
