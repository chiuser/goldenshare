# 上市公司公告同步完善 LLD v1

## 当前执行口径：Raw 保存全部源记录（2026-10-02）

管理员最新要求取代本文此前的完整度覆盖、group_key、CHECK/APPLY 身份迁移与性能优化方案。此前章节和生产试点记录仅作历史证据，不再执行。

- Raw 原样保留 Tushare 返回的所有字段到 raw_payload；只有所有源字段完全一致的记录才忽略重复插入。本地 id、fetched_at、api_name 不参加源记录比较。
- 比较完整源对象，JSON 对象字段顺序不影响身份；NULL、空字符串、空格、名称、URL、原始时间文本与任何额外字段的差异均保留。不同 URL 的两条同标题公告都保留，即使一条 URL 为空。
- 日期、代码、标题、URL、rec_time 缺失或日期时间解析失败均不得拒绝原始记录。查询列只是投影，无法投影时可空，原始值留在 raw_payload；不合成记录、不覆盖、不删除旧行。
- row_key_hash 为完整源对象规范 JSON 的 SHA256，唯一索引配合 INSERT ON CONFLICT DO NOTHING；冲突后核验完整载荷，哈希碰撞停止当前批，不能静默丢弃不同记录。
- 自然日 point/range 输入、每天分页、源字段显式请求六列不变。freshness 的 not_applicable 只表示不要求每天都有公告，仍支持日期输入。日期范围只有收到最后一个短页并提交完成凭证才完成。
- 执行 unit 为自然日，页上限2000，入库批500；内存受单页约束，业务每批短事务提交，末短页最后一批与日凭证原子提交。取消/退出保留已提交批，未完成日重放；重复重放不新增完全相同记录。源请求预算15000、每日500页、响应64MiB、源调用25秒保持现值，超过预算失败，禁止将截断结果报成完整。
- 进度仍显示阶段、日期、页offset、输入/插入/完全相同重复/拒绝数量、总量和更新时间；取消检查及25秒累计批事务期限不变。状态观察失败不得回滚业务数据，TaskRun/节点一致终态要求保留。

### 配置与影响面审计

storage 三项预算改名为 insert_batch_rows=500、insert_statement_timeout_seconds=25、insert_lock_timeout_seconds=5，默认在 DatasetDefinition，其他数据集为 None；不新增 env/Settings/数据库配置、CLI 参数或页面开关。消费者为 writer、AnnsDDAO、announcement_stream、linter、冻结执行合同和测试；发布后新任务生效，旧合同不得续跑。删除组版本128上限与全部分组消费者。

CodeGraph query/impact 已覆盖 transform、DAO、迁移服务及测试，源码补查 writer、stream、Normalizer、DatasetDefinition、工厂、Ops catalog/worker、下载器及视图。manual actions/catalog/workflow/resolver/planner/request builder/freshness/cards/snapshot/date audit/自动日期策略/前端时间控件继续消费既有日期合同，不自行构造分组或哈希。移除旧身份迁移维护动作、执行器及离线脚本，层间依赖不增加；服务视图名称和列名不变，日期/代码/标题允许空值。

### 数据库切换与验收

新增 Alembic183 接实际182 head，不自动删除任何业务表。旧记录的哈希口径不同，不能直接混写；迁移持表锁检查公告表为空才允许切换，非空则失败并保持原状。生产切换需要先停止公告写入，按管理员明确指令仅清理 raw_tushare.anns_d（管理员已取消备份），再升级183，以新执行合同按历史起止日期重新拉取。旧完成凭证属于旧执行token，保留也不会跳过新任务；禁止重用旧token。不做存量逐行重算或后置清洗。此前备份与恢复演练库按管理员本轮明确指令删除，不再要求备份或恢复演练。本轮按管理员最新明确授权已清空公告表、完成183迁移并删除指定备份；历史重拉尚未启动，服务重启仍需在部署阶段完成。

验收覆盖六字段及额外字段差异、NULL/空串/空格/时间文本、字段顺序、缺字段/非法日期保留、同批/跨批/跨页/并发完全重复、碰撞回滚、取消/退出/续跑、进度单调与状态失败隔离。真实源样本155162.SH/20230609（缺URL、有URL，均缺rec_time）应保存两条；源2=归一化2=首次插入2，重放插入0且完全相同重复2。全量历史完整性需生产重拉后以源分页计数、入库计数和拒绝原因读回对账确认，不能以代码测试宣称已经补齐。


### 本轮开发与验收记录

实现映射：anns_d_contracts 比较完整源 JSON，row_transforms 只建立可空查询投影，Normalizer 无损序列化且无法保存时失败，不静默拒绝。AnnsDDAO 批量忽略完全相同冲突并读回比对；writer/stream 沿用批次提交与完成凭证，计数为 processed=inserted+identical。storage 删除组上限，linter 检查三项新预算。Alembic183 对非空公告表失败，不清空、不重算旧记录，唯一索引与现有视图保留。旧 migration 服务、Ops 维护动作/执行器、App 注册与离线脚本已清退；旧迁移证据表保留为历史，不再读写。

- test_anns_d_exact_records：完整字段/额外字段差异、NULL/空串/空格/时间文本、字段顺序、异常字段保留、本地元数据无关、跨批/页/并发重放、碰撞回滚、真实进程退出续跑、旧合同拒绝、预算反例和新迁移非空保护。
- test_anns_d_stream：单页内存、分页 offset、取消/退出/续跑、短页凭证事务、状态观察失败隔离、累计事务期限、进度单调、请求预算。Web TaskRun 回归验证 success/failed/canceled 的活动节点与父任务一致，目录/手动动作回归验证旧动作清退。
- 本地源文档176六字段与 tushareMcp 核验：默认返回五字段，显式请求六字段含 rec_time；无日期 limit1、仅代码 limit1、点日 limit5、范围 limit1/offset1 均取得样本。保留源分页2000，未按 MCP 描述的6000擅自提限。
- 新鲜真实样本 155162.SH/20230609：source=2、normalized=2、rejected=0、首次inserted=2、physical=2；重放 inserted=0、identical=2，原始载荷读回相等。证据只在 /private/tmp/anns-exact-live-acceptance-20261002.json；不是 Prod 导出。
- 本地单日合成10001行、6页、physical=10001、完成凭证1；耗时约1.1秒、最长批提交事务约0.1秒。进程峰值含pytest，不能推算生产耗时或宣称RSS恒定。证据 /private/tmp/anns-p2-stream-performance.json。
- 注册、resolver/source、normalizer、writer/linter、freshness/catalog/snapshot、下载器、Worker/API与架构回归通过；文档完整性及 ingestion linter 通过。CodeGraph sync/status 正常，并查询确认 insert_ignore 新调用点。

生产公告表当前为空，必须新任务重拉后再做数量/拒绝原因读回对账；本轮不把本地验收等同于生产补齐。

### 取消备份与生产清空执行记录（2026-10-02）

管理员明确授权取消备份、删除prod公告备份并直接清空公告表。迁移183取消“必须先备份”的说明和错误提示，保留空表检查；不能为绕开迁移失败而允许新旧哈希混写。

已删除服务器 anns_identity_migration/20261002/anns_d-before.dump（551823900字节）、recovery-report.json及专用恢复演练库 anns_identity_restore_20261002_2102（仅含公告表及其索引/序列，删除前无活动连接）。小型历史审计报告保留，未删除其他备份或正式数据库。

再次检查无排队/运行公告任务并取得公告维护事务锁后，短事务仅 TRUNCATE ONLY raw_tushare.anns_d CONTINUE IDENTITY；未使用CASCADE，未清空其他表。随后执行已部署代码的 Alembic182→183，成功读回：Raw=0、Serving Light视图=0；group_key已删除，原始载荷非空约束生效，日期/代码/标题投影可空，主键及row_key_hash唯一索引有效；指定备份文件和恢复库均不存在。

服务器代码0c92804c，Python编译及只读存储门禁验证通过。Web仍为部署失败前启动的旧进程，本轮不自动重启服务或触发历史拉取；部署完成并加载新版后须创建全新执行合同的历史任务，不能复用旧完成凭证。此记录取代上文“本轮未执行生产清空”的旧阶段描述，不将清空或迁移成功认定为数据已经补齐。

> 以下为旧方案与历史执行记录，当前实施以以上口径为准。

更新时间：2026-10-02。状态：P1/P2及精简身份迁移已部署（Prod SHA 58750611，包含cb4f2216）；P4服务器小范围CHECK与备份恢复验证通过，2000行运行—取消—续跑—重放验收通过，全表CHECK通过；全量APPLY待阶段放行，P3真实同步验收未完成。最新生产证据见§14.7；此前记录保留为当时事实。物理去冗余按用户已确认的保守覆盖规则实施。[技术方案](/Users/congming/github/goldenshare/docs/datasets/anns-d-sync-technical-plan-v1.md)定义业务原则，本文件是实施与验收约束。按[开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)填写专项设计；0.3.5 摘要同步回原维护说明。

## 1. 目标合同及文件影响面

| 当前实现位置 | 后续改动 | 不得发生 |
| --- | --- | --- |
| src/foundation/datasets/definitions/news.py、models.py | anns_d 必填、按日 unit、具名执行/写入策略 | executor 内按 dataset_key 硬编码 |
| src/foundation/ingestion/row_transforms.py、normalizer.py | 可空时间/URL、类型化六字段指纹、质量样本 | 用 now() 补造时间、仅按键拒绝 |
| src/foundation/ingestion/unit_planner.py、request_builders.py | 日窗口规划、仅 start/end 映射 | Ops 展开日期、改成必须每日有数据 |
| src/foundation/ingestion/executor.py、source_client.py | 有界分页处理、取消、预算、业务凭证回调 | buffer_all；未经语义审计套用 staged_stream |
| src/foundation/models/raw/raw_anns_d.py、core_serving_light/anns_d.py、dao/factory.py | 物理有效集合、专项 DAO | 修改 RowKeyHashDAO 影响其他数据集 |
| 新增 foundation 公告同步 unit 凭证模型/DAO | 完成 unit 的业务凭证 | foundation 依赖 Ops FK 或任务状态机 |
| src/ops/runtime、ingestion adapter、task detail API 与 frontend | 恢复意图、进度/终态/统计迁移 | 状态写失败回滚业务数据 |
| src/scripts/announcement_download/source.py、ledger.py 及相关测试 | 只枚举有效版本、缺 URL 跳过统计 | NULL.strip()、已完成文件重复下载 |
| Alembic、数据集模板、原开发/PDF文档 | 模型/真实表/消费者同步迁移 | 猜 head、双轨哈希或清空业务表 |

目录路径是已核验入口；新符号名称在 P1 引入时明确。CodeGraph 动态引用不完整，按本表与源码引用审计补全。没有新增依赖方向、Worker、lane 或 systemd unit。

## 2. 六字段归一化、身份和覆盖算法

ann_date 转 date；ts_code 去首尾空白并大写；title/name/url 沿用去 NUL/首尾空白，不模糊标题，不改 URL 协议、query 或路径大小写。空串与源 NULL 归一为 NULL。必填 ann_date/ts_code/title 缺失拒绝，URL 格式异常保留原字符串并告警，不当成有效可下载链接。rec_time 解析按 Asia/Shanghai，转带时区时间；空值为 NULL；非法可选时间为 NULL，raw_payload 保留原值，并记录 quality.invalid_rec_time。原始载荷不得由合成行替换。

group_key=SHA256(类型化 JSON 数组[dataset_key,ann_date.isoformat(),ts_code,title])。row_key_hash=SHA256(类型化 JSON 数组[dataset_key,ann_date.isoformat(),ts_code,name,title,url,rec_time规范化ISO])。固定 UTF-8、无多余空白、保留 Unicode、显式 JSON null，不使用会歧义的分隔串或字符串 NULL。全部规范时间转 UTC 以消除等价时区差异，原时间文本保留在 raw_payload。这套六字段身份全量替换旧公式，不保留哈希版本双轨。

哈希只是索引加速：命中已有 group/hash 时核对实际字段；不同内容同 hash 则结构化失败，不做覆盖。对于非法时间原文不同、但六字段规范结果相同的样本，不应丢掉原文差异：同源指纹下 raw_payload 保存有界诊断样本（每理由3条），计质量告警；不承诺归档所有抓取原文或无限载荷。完全重复统计指规范六字段相同，必要清理前的原文细节只作证据。

定义 covers(B,A)：同一实际 G；A 的每个非空 V 属性等于 B；B 的非空属性集合严格包含 A。有效集合 current(S)={r∈S | 不存在s covers(s,r)}。名字不同不能互相覆盖。只做偏序覆盖，不对兼容但互不包含的记录合成字段，不用最后写入时间决定保留。

算法处理一批：归一化→按指纹识别完全重复→按group_key排序分组→锁住组→读取现有组候选（LIMIT129）并核验实际字段→并入本批输入→求极大元→跳过新残缺/重复→按显式id删除库内被覆盖行→插入尚不存在的极大元→原子提交。组现存或本批不同内容的联合候选超过128时报group_version_limit_exceeded，先失败、不删除、不截断。处理量最多一个源页及500写入行、一个128版本候选组，不全表/全日期加载。删除条件为被覆盖/完全相同的显式id清单，加实际group键条件；禁止按标题、日期范围直接批量删除，禁止删除非空冲突行。

重要性质：max(max(S)∪T)=max(S∪T)，所以不需要保存先前被覆盖版本，也能保证跨页和输入顺序无关。相同范围和源输入重放后的六字段业务集合相同；自增id/抓取审计时间不要求跨不同初始库相同。已有效行不被后来的残缺版本降级。增加完整信息可能让物理行数减少，进度应以已提交输入/完成unit单调计，不能用物理行数当累计完成量。

## 3. 物理与读取模型

raw_tushare.anns_d保留id、现有六字段、api_name/fetched_at/raw_payload；新增group_key(char64)索引，URL和rec_time改nullable。row_key_hash唯一但统一换六字段公式；不新增is_current/covered_by_id，不建立源历史版本表。实际源字段在group/hash命中时核验，哈希不同内容碰撞失败。删除冗余时不把旧载荷追加到保留行；raw_payload只保存当前保留源版本及有限质量诊断。

core_serving_light.anns_d仍是同名普通视图，沿用现有字段和source/fetched_at，无需有效标记过滤。Raw本身就是保守覆盖后的物理有效集合。冲突版本均为有效行；完全相同保留已有id，新增完整版可用新id替代残缺id，存量引用消费者必须适配可能失效的Raw id，不能隐含永久实体身份。

迁移候选设计表raw_tushare.anns_d_identity_migration：migration_token UUID、raw_id bigint、old_hash/new_hash/group_key char64、action（keep/delete_identical/delete_covered）、survivor_raw_id bigint nullable、applied_at timestamptz nullable；唯一(migration_token,raw_id)。只保存身份和动作映射，不复制被覆盖公告全文成常驻业务历史库。header记录冻结状态、contract_digest、high_water_id、候选数/保留数/删除数、清单摘要。按完整候选组计算极大元，完全重复保留最小已有id；被覆盖行survivor仅为迁移审阅映射，不成为生产业务外键。

执行前核验原表无并发写、候选完整、每个删除有实际字段覆盖证明、每个冲突版本在keep集合、最终keep的新hash唯一。真实不同字段同hash碰撞失败；新hash相同且字段相同按完全重复物理去重，是本次用户已确认原则，不再以它为拒绝整次迁移的理由。候选先冻结后APPLY，每组在一个短事务内完成keep哈希更新、delete动作与凭证。单组上限128；写批500，不跨组拆开原子决策。

迁移中旧唯一索引对新hash中间态可能冲突：维护窗口内先冻结校验最终唯一映射，受控移除旧唯一约束/索引后逐组变更，业务领取停止且没有其他写入；完成后建立/校验唯一索引并验证全部keep映射、物理集合及视图，之后才允许新代码写入。禁止给中间行造临时业务hash或开放双轨写。中断保留applied_at，按冻结清单恢复续跑；索引缺失期间不开放写入。

物理删除不可仅靠身份映射恢复原字段，因此P4具体执行前必须有针对该表与迁移范围的可验证恢复备份及恢复演练，再生成清单获准APPLY。备份是部署恢复材料，不是日常版本保留；工具、位置、保留期和清理授权在执行方案明确。没有恢复资料不得执行删除，不自行清理备份、不调用Kopia。当前旧hash已可能覆盖name差异，历史丢失仍靠重拉源补回。

业务完成凭证设计表 raw_tushare.anns_d_sync_unit：execution_token UUID、contract_digest char64、scope_hash char64、ann_date date、attempt_token UUID、terminal_page_number、terminal_offset、terminal_rows、rows_observed、rows_committed、reason_counts JSONB、completed_at timestamptz。唯一(execution_token,contract_digest,scope_hash,ann_date)。只保存完整完成事实，无 queued/running/failed 状态，无 Ops FK，不成为 TaskRun 替代。execution_token由组合适配层生成并透传，foundation当作不透明token。完成凭证随最后业务批提交；空日短页仍提交凭证。重试不清空凭证或日期范围；重放仍按同一覆盖规则处理有证明的冗余。

## 4. 日窗口、事务、预算与取消

resolver冻结升序日列表及scope_hash（日期范围、代码过滤、数据集/合并合同指纹），point=1，range=end-start+1；无日期入口仍不支持。date_model 的自然日输入、not_applicable freshness、ann_date观测三层保持分离。规划超3,660天立即拒绝，不能先运行再扩计划。

一页源返回最多2,000，分最多500行批，每批事务包括保留行插入及同组冗余物理删除；页中断保留此前已提交批，页不得标完成。最后短页的最后批与 unit 凭证原子提交。空页单独短事务写完成凭证。整日不持有数据库事务。未完成日已提交批可见，因此Raw/view是当前已观察记录的物理有效集合，不承诺未完成日是源端完整快照；完成凭证另表表达观察窗口完成。UI/下载不得把已有有效行误报整日同步完成。HTTP请求前关闭先前SQL事务，避免此前14075的长idle-in-transaction。

announcements专项分页策略须在Definition/合同中具名，不让通用executor猜数据集。现有 staged_stream 在进入时 clear_stage，且按period和snapshot finalize；不能直接用于追加式公告和续跑。复用其独立业务session原则，但采用有界逐批追加/覆盖策略，不复用清空stage、整期replace语义。

并发：同一数据库所有 anns_d 维护执行串行，用数据库会话级try advisory lock保护整个执行；争用不等待，返回dataset_busy，不持有长事务。迁移也取得同一锁。普通读不被这个执行锁阻塞。单批组行锁/组键锁保持固定顺序，初始化空组也锁实际group key；发生锁冲突/超时回滚当前批，不能绕锁。连接死亡锁自动释放，TaskRun终态由runtime恢复处理。

请求timeout目标25秒指整个不可分割调用的deadline，包含连接、响应读取和解码，而非仅requests的read inactivity timeout；需要在P2适配显式deadline与可关闭的流响应，慢速持续返回也不能无限延长。检查取消在每页、每写入批、每重试前后和等待间隔内；DB statement/lock预算分别25/5秒。单次解析/比较超过30秒须拆分或安全中断，不能心跳掩盖不可取消步骤。最大页响应64MiB需在connector传输阶段限制，不能完整解码后才检查；decoded峰值用内存实测验收。只承诺与单页/批相关，不宣称64MiB就是进程RSS上限。

## 5. 配置审计（新增设计，P0没有运行配置）

新增数字不能散落DAO/页面/脚本。下列值均归属一个anns_d具名执行策略对象，在Definition持久化源码，计划冻结快照；默认不新增env、DB配置或运营参数。Definition→resolver/执行器/DAO/connector是消费者，不改其他数据集默认。

| 配置名（设计） | 默认 | 消费者、依赖与运维可见性 |
| --- | --- | --- |
| page_limit（现有） | 2000 | 源分页；固定现有契约，不提高到MCP元描述的6000 |
| write_batch_rows | 500 | writer/DAO；不能超过page_limit；计划快照展示 |
| max_units_per_execution | 3660 | resolver预检；按日总量，上限原因可见 |
| max_pages_per_unit | 500 | executor；包括结束空页，每unit限制 |
| max_source_rows_per_unit | 1000000 | executor；累计源返回行，重复行也计 |
| max_requests_per_execution | 15000 | source计数；含失败尝试/重试，重启恢复仍继承累计预算 |
| max_response_bytes | 67108864 | connector传输限制；decoded另实测 |
| max_group_versions | 128 | DAO；LIMIT129检测，不截断后成功 |
| source_call_timeout_seconds | 25 | anns_d源调用；与取消30秒门禁关联 |
| db_statement_timeout_seconds / db_lock_timeout_seconds | 25 / 5 | 专项业务事务，不改全局Settings |

生效：新计划读取Definition策略并冻结；同一计划恢复校验digest，策略变更不静默复用旧凭证。关系：每日page/row上限和每执行request上限共同约束；预算超限保留已提交数据，失败reason及阈值显示。现行配置审计：Settings.tushare_token/base_url/max_calls_per_minute分别来自TUSHARE_TOKEN/TUSHARE_BASE_URL/TUSHARE_MAX_CALLS_PER_MINUTE，源码默认空/https://api.tushare.pro/280，环境文件加载走现有Settings（不输出凭据、不声称本机值就是Prod值）；TushareHttpClient和全API限流器消费，anns_d没有_API_RATE_LIMITS单独覆盖。重试是SourceClient源码常量max_retries=3、普通退避0.5秒指数、限流等待65秒；HttpClient默认连接/读取timeout=(5,30)，HTTPAdapter又有total=5的隐式重试。这些是当前实现事实，不能满足25秒与精确请求预算。目标anns_d具名策略只启用显式可取消重试，禁止HTTPAdapter对其隐式重发；每次真实尝试都先预占预算，普通/限流等待沿用时长但拆成可取消短等待并报告阶段。认证和全API限流复用现行Settings，不添加第二套凭据或速率默认；其他API行为不得被anns_d迁移改变。所有参数的具体适配/调用方测试在P2实施。若既有connector不能传逐数据集timeout/响应预算，P2显式迁移其合同和全部调用方，不用临时HTTP绕开。此项不影响P0完成，但未核完禁止改配置或接口。

重启累计预算依据不能只在Ops计数：业务凭证只保存完成日不足以覆盖失败尝试。因此设计新增同表配套请求预算账 raw_tushare.anns_d_sync_request_budget，execution_token唯一，issued_requests bigint、updated_at；每请求前独立短事务原子预占1，失败/取消也不退预算。业务提交不依赖Ops，预算表不保存TaskRun状态，崩溃最多保守多计一次，不会绕过总量上限。数据库不可用不发源请求。本需求专用两种业务凭证必须在P1容量/消费者审计中完整列入迁移清单，不推广为所有数据集通用框架。

## 6. 恢复、进度与终态

只有同冻结执行execution_token、scope_hash、contract_digest才允许跳过有完成凭证的日；unfinished日offset从0。新维护任务即使日期相同也是新观察，不能跨任务永久跳过。续跑关联只由运营明确表达，Ops保存意图并由resolver核验来源范围/过滤/digest；自动日任务不默认关联历史任务。恢复意图目标schema：Ops维护提交请求顶层可选resume_from_task_run_id（正整数、默认NULL），不放进源filters或Tushare请求。Ops核验原任务属于anns_d.maintain、已停止执行、调用方具有现行运营权限，读取原execution_token并将范围/过滤/digest交resolver校验；不匹配拒绝，不支持running任务并行恢复。新TaskRun独立保存恢复意图及来源任务ID，共享业务execution_token，原TaskRun历史不改。API、手动表单、CLI、自动workflow及所有提交方的P2迁移结论见§12；Prod尚未部署，不以本地完成声称生产已可使用。

进度阶段：planning、fetching、persisting、reconciling、completed/canceled/failed。展示当前日期、页号、源返回量、已提交输入量、新增保留版本、完全重复、残缺覆盖、冲突组、无URL/无时间、质量告警、完成日/总日/百分比、最近更新时间。百分比按完成日凭证；进行中的日显示具体页/量；总源行未知，不报源行百分比。ETA显示暂无法估算，达到代表性样本后再评估，不能预设倒计时。

计数分层：每次源返回行必须归入已提交输入/未提交输入/真拒绝；重复重放的提交输入是处理量，不是新增公告。本批每条合法输入按新增保留版本、完全重复或被覆盖输入归类；对库内原行的删除量另计，不能重复计入本批输入等式。当前有效公告数量是读回状态，可能下降，不能作为单调业务进度。冲突是组级告警不叠加到行数等式；缺URL/时间是可重叠质量计数。P3对账源输入、规范输入与物理输出三个口径，不用一个rows_saved混算。

Ops观察更新独立session；提交后报告，失败只告警不回滚业务。每页开始、结束、每批后有业务进度；请求最长25秒，确保30秒内可见更新。runtime在成功/失败/取消同事务更新TaskRun和当前节点终态；若观察库不可用，保留业务完成凭证并由既有恢复路径修复，不假造已写终态。关闭进程后恢复当前状态不是自动续跑生产业务，恢复执行仍需要明确意图。

reason code设计：quality.invalid_rec_time、quality.missing_url、quality.missing_rec_time、merge.identical、merge.covered、merge.conflicting_attributes、anns_d.group_version_limit_exceeded、anns_d.request_budget_exceeded、anns_d.response_size_exceeded、anns_d.identity_collision、anns_d.dataset_busy。新增时同步codebook，quality/merge不等于rejected；必填缺失沿用已有code。最终拼写和API统计映射P1/P2实现前冻结，不能只有文档存在。

## 7. 存量迁移、发布和恢复

先检查真实Alembic head，新增迁移只能接真实head。P1演练生成按raw_id分页的映射候选和只读报告，含当前总量、新指纹重复、名称差异、组版本上限、预计有效量/覆盖量、索引大小、迁移耗时及冲突样本。计划覆盖当前所有anns_d数据，不只14075日期范围。保存候选后校验并冻结才可APPLY；候选路径、物理表清单、空间、逐批恢复凭证在演练中固定，不先写Prod再补。

部署按“停止领取公告任务且等待旧任务退出→备份/恢复方案与权限确认→增量结构→分批身份/组投影迁移→校验→切换六字段写入及有效视图→适配消费者→代表性验收→恢复领取”。迁移与业务写不能使用两套身份同时运行。维护窗口内禁止新脚本消费未完成的有效投影，不新建公共开关。保留仍有效行的id，物理去除已证明的冗余；冲突版本不删除。

恢复：DDL允许空值后旧程序仍可能错误拒绝，不能退回旧逻辑当作成功回滚。新NULL数据存在时不收紧NOT NULL；身份迁移出错保留批次候选与凭证、停止新写，按冻结映射继续APPLY或依获准恢复备份还原，不能truncate重建或恢复旧哈希双轨写入。恢复方式必须区分只更新哈希与已经删除原行；不能声称仅凭映射可以撤销物理删除。迁移清单已在§3明确，不能在执行中临时扩大删除范围。

代表性生产授权另行取得。历史补录选择日期范围/代码、预算和执行token，先小范围运行—取消—续跑—读回，再分批历史范围。14075历史记录保持原结论，不改计数伪装本次成功。拒绝样本有限，补历史重新请求源；源变动可能使最终数量不同。

## 8. 硬要求追溯与测试矩阵

| ID / 硬口径 | 代码点 | 正向 / 负向验证（阶段证据见 §10） |
| --- | --- | --- |
| A01 缺url/时间可保存 | Definition、transform、ORM/DDL | 各缺、都缺；不造日期/链接 |
| A02 完整覆盖残缺 | 专项DAO、有效view | 155162.SH样本；日期/标题不同不得合并 |
| A03 非空冲突保留 | 覆盖算法 | 两URL、两时间、两名称；不能按分数选一条 |
| A04 不合成源行 | payload与覆盖算法 | 互补残缺保留两条；完整C到来再覆盖 |
| A05 顺序与跨页无关 | group锁、批提交、指纹 | 枚举输入排列/分页切分，输出相同；重放无新增 |
| A06 物理去冗余与单一身份 | hash/group/id、迁移 | Raw仅极大元；存活id保持、被替代id可失效；字段碰撞失败；删除rollback无半成品 |
| A07 日窗口不等于完整性桶 | resolver/builder、freshness消费 | point/range、空日成功；不要求每天公告 |
| A08 内存/请求有界 | executor/connector/预算DAO | 大量页RSS稳定；每个阈值超限报失败而非截断成功 |
| A09 取消退出续跑 | 业务凭证、runtime | 第500行后/最后页前/commit后崩溃；保留提交、未完成重放 |
| A10 观察独立与终态 | 适配层TaskRun/node | 状态写失败不回滚、恢复读回、终态一致 |
| A11 进度真实 | progress/API/frontend | 30秒更新、单调完成日、有效数减少不当失败 |
| A12 消费者适配物理替代 | view、PDF source/ledger | 被删id不领取；NULL不崩；新版本同URL不重复下载；新轮次重枚举 |
| A13 新观察不误跳 | resolver/恢复输入 | 同计划跳完成日；新任务同范围仍请求；digest错拒续跑 |
| A14 源代码不限股票池 | transform/filters | S1649.SZ和155162.SH可存；非法必填仍拒 |

本地测试计划：现有Definition、resolver、source_client、normalizer、writer、row_key_hash DAO、Ops action/API与架构/codebook门禁；新增anns覆盖DAO与业务凭证事务故障测试；PDF CLI专项。UI如变更必须做真实浏览器取消/续跑和进度可见性验证。测试路径存在性先确认，不安装包或隐式同步依赖。

最小真实验收：155162.SH/2023-06-09两源版本→Raw物理一条、view一条，内容来自有URL的源版本；S1649.SZ/2024-12-31缺时间有URL正常保存；选第二页真实样本校验源参数/分页；代表性多页范围执行取消续跑并按指纹集合读回，峰值RSS、API更新间隔、调用超时及数据库事务长度记录到原维护说明。覆盖源/normalize/commit/raw/current计数与每种理由；没有可信全集基准时不得宣称源站全集完整。

## 9. P0完成判定与未执行项

P0只验收事实核验、决策表、影响面、配置设计、0.3.5、迁移边界和测试计划；本轮文档检查结果由交付消息记录。P0 当时未执行 P1—P4；最新 P1 源码及隔离验证见 §10。P2 长任务改造、P3 代表性生产验收及 P4 存量 APPLY 仍未执行。待后续具体化的是实现/部署证据，不把未实施设计写成已支持功能。


### 2026-10-02 P0验证记录

- python3 scripts/check_docs_integrity.py：绝对链接、DS_Store、Tushare索引三组通过。
- git diff --check：通过；另逐文件检查本轮6份文档含新增未跟踪文件的尾随空白及末尾换行，均通过。
- 临时独立规范模型检查：7个组内覆盖场景，22种输入排列及各自重复输入检查通过。模型只实现§2偏序，未调用生产DAO，不代表源码测试、性能验证或跨组数据库验收。
- 核对技术方案、LLD、原维护说明、PDF两文档及主索引：现行/目标/历史证据分开；旧buffer_all和必填行为保留为现行说明；原PDF M1不升级为新合同已兼容。
- P0文档范围完成；P1—P4及PDF后续阶段均未执行。没有源码、迁移、配置、Prod、Lake或外盘变更；未提交或推送。


### 2026-10-02 用户拍板后的P0修订

物理只留极大元，残缺冗余不保留原始业务副本；非空冲突按保守规则分别保留。删除语义只在已审阅的冗余判定内，生产存量执行仍需具体清单/恢复方案和阶段授权。取代前版的is_current/covered_by_id证据留存设计，尚无对应代码或DDL，因此本次只需更新文档，不执行撤销迁移。

修订验证：文档完整性和diff空白检查通过；独立规范模型7场景、22种排列，逐行只保留极大元并重放，六字段结果一致。未执行源码/数据库测试、迁移或生产删除。


## 10. 2026-10-02 P1 实现与验收账本

P1 源码与隔离验收完成；授权扩大窗口后，生产有界存量样本 PLAN 演练通过；全量生产迁移清单与容量/耗时验收未完成，不得据此放行 APPLY。当前 range 仍是完整区间 unit、buffer_all、unit commit；DAO 内的 500 行分批是计算/写操作分批，不是独立业务提交。P2 完成前禁止据此运行生产大范围回补。

| 硬口径 | 实际落点与证据 | 尚未完成 |
| --- | --- | --- |
| A01/A14 | Definition 只要求三业务字段；transform 可空 URL/时间，非法可选值告警；normalizer 原始 payload、质量理由各最多3条；必填缺失仍拒，S1649.SZ 不按股票池过滤 | Prod 新结构发布 |
| A02/A03/A04 | anns_d_contracts.py 类型化指纹与 covers/maximal；AnnsDDAO 求真实源行极大元，不合成字段；非空冲突分别存储 | 历史全范围读回 |
| A05/A06 | 输入排列/重放、跨批物理替代与存活 id、哈希不符失败；同组 advisory lock 含空组；savepoint 验证删除后插入故障整体回滚、超限不删 | 执行级串行锁与短提交属 P2 |
| A12 | Raw/view 可空模型；PDF 无 URL 保存映射且不请求，领取按文件身份复查、旧 id 不当永久身份；旧文件复用逻辑回归 | Prod 查询性能/真实下载属后续阶段 |
| A07—A11/A13 | 既有 resolver/source/目录/架构消费者回归通过，输入与时间模型不变 | 日规划、分页提交、凭证、预算、取消续跑、30秒进度与终态均属 P2/P3，未验收 |

P1 配置审计落实到 DatasetStorageDefinition：reconciliation_batch_rows=500、reconciliation_max_group_versions=128、reconciliation_statement_timeout_seconds=25、reconciliation_lock_timeout_seconds=5。通用字段默认 None，仅 anns_d 注册；来源/持久化为 Definition 源码，writer 透传、专项 DAO 消费，离线 PLAN 消费批次/组上限，linter 校验正整数。没有 env、Settings、数据库开关或运营参数；新进程加载 Definition 生效。当前没有计划冻结预算快照，P2 再迁移，不能声称恢复已校验 digest。§5 中其他执行预算仍是设计值。normalization.preserve_raw_payload 默认 False，anns_d 为 True，只有 normalizer 消费。

新写路径 raw_only_reconcile 由 Definition 选择，writer 不按 dataset_key 分支，仅取 Raw DAO；不访问 serving DAO。不改 RowKeyHashDAO，其他三个公告/研报类 DAO 仍沿用原路径。空输入不写业务行；未完成身份迁移仍拒绝进入专项 DAO。processed=inserted+identical+covered 是合法输入处理量；rows_written/上层 saved 采用此口径，非最终物理行数。inserted 是插入事件数，可被后续批覆盖；deleted 单独计；conflicting_group_visits 是遇到多个极大元的组访问次数，跨批可重复，不能当唯一冲突组数。质量计数可重叠、不加到拒绝数。P2 需迁移任务展示/聚合。

迁移 20261002_000181 接开发前实际 head 20260916_000180；只扩展可空列、nullable group_key/index 和身份候选/header 两表，不 backfill、删除或拆旧唯一索引。P4 在冻结清单、无并发写、恢复方案就绪后统一更新身份，校验后 SET group_key NOT NULL；DAO 用此结构条件作为就绪门禁，不开放旧新混写。ORM 描述最终 non-null 结构，扩展期明确不同；自动 downgrade 被阻断，防止删除映射或收紧已写 NULL。

离线工具 src/scripts/plan_announcement_identity_migration.py 只读人工审阅 JSONL，SQLite 按组有界计算；保留最小已有 id 的完全重复，覆盖行记录明确 survivor，冲突不删。输出不可覆盖，冻结 token/合同/高水位/数量/清单及输入摘要；verify_plan 只读校验外部预期摘要、数量与 survivor 引用，篡改失败。临时输入 spool 冻结后移除，只留下身份动作映射。合成四行演练得到 keep=2、delete_identical=1、delete_covered=1；这不是生产全量 PLAN。P4 的生产分页导出、候选上传/APPLY、维护窗口与备份恢复尚未实现。

两种后续业务账表也纳入影响面：anns_d_sync_unit 的基数为 execution×日期，末批消费/同事务提交；anns_d_sync_request_budget 的基数为 execution，每次源尝试独立预占，source/executor 消费。均不与 Ops 建 FK，P2 创建/实施；当前 P1 迁移未创建这两表。实际容量仍需执行 token/范围和请求统计测量，不能用 TaskRun 状态取代。

真实源复核：Tushare anns_d 请求 ts_code=155162.SH、start_date=end_date=20230609、六字段、limit=3/offset=0 返回2行，均 rec_time=NULL，一行 url=NULL。将这两条真实六字段样本送入隔离 PostgreSQL：源2→normalize2→合法处理2→Raw1/view1，reject0、inserted1、covered1；保留有 URL 的真实版本及其 payload，不补时间。源站访问只读，不是 Prod 同步运行。

验证：现有虚拟环境回归 406 项全部通过，包含专项真实 PostgreSQL、DDL 扩展门禁、并发、rollback、Definition/normalizer/writer/通用 DAO、resolver/source/Ops catalog、架构与 codebook、PDF CLI。PostgreSQL 18 使用独立 /private/tmp/anns-p1-pg-20261002 与独立 socket，测试 URL 受临时路径门禁限制，不连接本机既有或生产库；结束时停止该集群。未安装套件。

生产容量仅查询系统目录：raw_tushare.anns_d reltuples 估计7,977,294行（非精确 COUNT），table_bytes=2,580,774,912、index_bytes=1,491,623,936；既有 id/hash/date/code-date/rec-time 五个索引。READ ONLY、statement_timeout=15s，只返回一行容量与五行索引定义，未导出公告记录。按500行估计至少15,955个输入批，完整迁移不能用单事务；新 group 索引、SQLite spool/映射峰值空间、迁移耗时及实际冲突样本仍需生产样本演练测量，不能用此目录估计放行 APPLY。

原拟导出 600000.SH/2026-05-12—14、id/旧hash/六字段、最多129行至 /private/tmp 的样本，被自动审批以“缺少具体生产数据及本地导出目的地授权”拒绝，命令未执行。此验收项保留待授权；未改成其他路径或方式绕过。P1 本地交付可审阅，生产存量演练门禁未关闭。

影响面核验使用 CodeGraph status、query/callees _anns_d_row_transform、impact RawAnnsD、query _write_raw_only_upsert、callers bulk_upsert；动态 factory/registry 补源码搜索。Raw/view 的直接消费者是模型注册与 PDF Source，未找到业务 API/前端直接以公告 id 读取正文；Ops catalog/workflow/resolver/freshness/cards/snapshot/audit 继续消费不变的输入/日期/观测字段。本仓库消费者已适配/回归，仓库外 SQL/id 引用仍需发布前人工核对。未新增依赖方向、Worker/lane 或 systemd。


最终补核：四个预算非法值（0、负数、None、bool）及不保存原始载荷的配置反例共5项通过；PDF source_record_replaced 理由已持久化，保留原文件状态。相关本地复核72项通过、1项临时 PostgreSQL 用例跳过、8项不在此补核范围；此前全套406项已在启用临时 PostgreSQL 的环境通过。Definition lint、唯一 Alembic head、文档完整性和 diff 空白检查通过；CodeGraph sync/status 显示最新。任务临时测试集群已停止。没有提交、推送、部署、生产迁移或正式外盘写入。


### 2026-10-02 指定生产样本授权后的演练

用户明确授权此前指定导出：raw_tushare.anns_d，600000.SH，2026-05-12～2026-05-14，投影 id/row_key_hash/六个源字段，最多129行，输出 /private/tmp/anns-p1-prod-sample.jsonl。经现有 bash scripts/psql-remote.sh 入口执行 BEGIN READ ONLY、statement_timeout=15s，结果0行/0字节；没有扩大日期、对象、字段或行数。上一轮自动审批阻断已解除，当前缺口是该窗口无样本。

离线 PLAN 生成 /private/tmp/anns-p1-prod-sample-plan.sqlite，candidate=0、keep=0、delete=0、高水位0，已冻结；verify_plan 按独立读取的清单摘要核验通过。报告 /private/tmp/anns-p1-prod-sample-report.json 记录范围、字段、数量和冻结摘要。只能证明空输入路径，不代表生产有数据样本通过、全量范围为空或日期连续完整。真实存量演练仍需另一个明确获准的有数据窗口，P1 门禁保持未关闭。生产无 DDL/DML/APPLY，源码与依赖边界未变，未提交或推送。


### 2026-10-02 扩大窗口后的真实存量 PLAN 结果

用户再次明确授权同一公司扩大至2026-01-01～2026-09-30、相同字段、最多129行。经现有 psql-remote 入口在 BEGIN READ ONLY、statement_timeout=15s 下导出，得到68行（30,944字节），未触及LIMIT；没有扩大对象或字段。样本文件 /private/tmp/anns-p1-prod-sample-expanded.jsonl。只代表本次数据库快照该对象/窗口的存量，不证明源站全部公告均已存入。

离线 PLAN 输出 /private/tmp/anns-p1-prod-sample-expanded-plan.sqlite：候选68、保留68、删除0、高水位2061408；56个候选组，最大每组2条。12组各有两个版本，仅 rec_time 非空值不同，name/URL相同；按保守规则不能互相覆盖，全部保留。该样本不存在缺URL/缺时间、完全重复或残缺覆盖，相关路径仍引用前述真实源缺值样本、合成PLAN和隔离DAO测试，不用本轮替代这些验证。

现行 normalizer 复核源68→归一化68→拒绝0→极大元68，质量告警0。全部68条旧hash改为六字段类型化新hash；只生成映射，未写回原表。冻结清单摘要13788a4e7971f82733847b83dc2675bbd5e6510e07819f9195f4b905418ff6cb，输入摘要19e3cbb2f99025ae6273fce4d637b3a2020cd5b333ea4ad514377ac99085a12b。verify_plan只读核验摘要、数量和survivor引用；独立逐条核验实际字段/新身份及最终六字段极大元集合，均通过；所有applied_at仍NULL。

本地PLAN耗时0.020345秒，SQLite产物102,400字节，整进程峰值RSS152,420,352字节（包含Python/依赖加载，并非PLAN净内存）。该小样本不得线性外推约798万行全量索引/临时空间、生产DDL或APPLY耗时。报告 /private/tmp/anns-p1-prod-sample-expanded-report.json 保留范围、计数、质量、冲突字段类型、时间/空间、合同和摘要证据。

本次授权样本演练完成，前述空窗口/授权阻断为历史记录；全量冻结候选、空间测算、恢复演练及生产APPLY仍待P4具体执行方案和授权，P2长任务改造未执行。更新本LLD、技术方案和维护说明；源码与依赖矩阵未变，Prod没有DDL/DML、迁移或删除，未提交/推送。

## 11. P2 开发约束与配置落点（本地实现与验收完成）

本轮仅实施 §4—§6 与 A07—A11/A13：自然日 unit、500 行短提交、业务完成凭证、持久化请求预算、执行锁、取消、同执行续跑及任务展示；不执行生产迁移或回补。要求—代码—测试对应：日上限/参数→planner/builder/resolver→point/range/超限/空日反例；预算/超时/响应上限→Definition/source/connector→超限、重试计数、慢流期限；提交/凭证→专项执行器/业务 DAO→中途取消、退出、末批失败、重放；恢复意图→Ops创建/dispatcher→运行中/其他对象/范围与digest不符拒绝，新观察不跳；观察隔离/终态→context/runtime→状态写失败不回滚且TaskRun/node终态一致；展示→query/schema/frontend→阶段、当前日/页、单调完成日、更新时间与无可靠ETA。

P2新增 planning.announcement_policy：max_pages_per_unit=500、max_requests_per_execution=15000、max_response_bytes=67108864、source_call_timeout_seconds=25；来源为DatasetDefinition源码，默认None，仅anns_d启用，builder转换为具名policy对象，resolver冻结到计划及合同摘要，stream执行器/source/connector消费。现有planning.max_units_per_execution=3660、max_source_rows_per_unit=1000000、page_limit=2000、fetch_concurrency=1；storage四项P1预算沿用并冻结，不创建第二份500/128/25/5默认。没有新env、Settings、DB配置或运营限流输入。变更policy后已有执行digest不符则拒绝续跑，运营通过既有任务详情查看预算/失败reason。

页处理mode=announcement_stream、commit_policy=batch；通用默认与其他数据集不变。新增execution_context仅作为内部冻结合同透传，Ops API只接受顶层resume_from_task_run_id（默认NULL、严格正整数），源filters拒绝该字段。业务表anns_d_sync_unit和anns_d_sync_request_budget不保存TaskRun状态、不与Ops建FK；表生命周期及容量按§3/§5执行。

传输适配必须复用TushareHttpClient、现有凭据与限速器。隔离的单次调用执行可中止的总期限，禁止HTTPAdapter隐式重试/重定向绕预算；64MiB在读取响应时限制，解码也在期限内。所有实际尝试先预占持久化预算；限速、重试等待以短间隔检查取消并更新阶段。新增call_bounded能力只由该具名策略消费，原call及其他connector消费者保持原行为。


## 12. P2 实现、消费者与验收对账（2026-10-02）

本阶段源码与本地隔离验收完成，未提交、推送或部署。§10 保留 P1 当时的完整区间执行事实，当前源码已经切换为下表的日窗口流式执行。Prod 结构/存量身份尚未迁移，入口会以 identity_migration_required 拒绝写入，包括空日，不允许先写完成凭证。

| 硬口径 | 实际代码与消费者 | 正向及禁止项验证 |
| --- | --- | --- |
| A07：自然日 unit、单页/批边界 | news.py 的 build_announcement_units、announcement_stream、batch；unit_planner、_anns_d_params、source_client、announcement_stream | point/range 参数、3660 天超限先拒绝；每页 2000、批 500，500 条取消读回仍在；未完成日 offset 0，完成日无 HTTP 请求 |
| A08：空日和末批原子凭证 | anns_d_sync_unit、AnnsDSyncDAO.complete；末短页/空页与末批同事务 | 空日凭证；末批凭证故障只回滚末批；进程退出留住前批，重启重放无重复；真实源两版本物理只留有 URL 一条 |
| A09：预算、期限、串行 | AnnouncementExecutionPolicy、request_budget、TushareHttpClient.call_bounded、bounded_tushare_call；执行级 pg_try_advisory_lock | 预算持久耗尽后重复续跑仍拒绝；每次重试预占；页/行超限、重试等待取消；实际回环 HTTP 无重定向/隐式重试，读中限制字节，持续慢流被总期限终止，无残留调用进程 |
| A09：短业务事务 | bounded_business_batch 的连接 SQL deadline；沿用 storage.statement_timeout=25/lock_timeout=5 | 跨两条 pg_sleep 累计超时，当前事务回滚；不是每个组重新获得 25 秒；请求等待前释放业务事务 |
| A10：观察隔离和终态 | TaskRunIngestionContext、dispatcher、OperationsWorker、query/schema | 观察失败不影响业务保存；TaskRun/node 成功/失败/取消一致；保存前批统计；诊断过大仍保留阶段、日/页、完成量、更新时间 |
| A11/A13：同执行恢复与新观察 | announcement_scope、resolver、Ops service/API/manual schema、manual tab | JSON 往返合同一致；旧任务 running/非公告/无合同拒绝；日期、ts_code 或 digest 不符拒绝；严格正整数 ID；新提交 token 不同，不永久跳过历史日 |
| A10：真实浏览器展示 | task detail、OpsAnnouncementProgress、manual tab；消费 query 的 announcement_progress | 本地 Playwright 真实页面读取/保存阶段、完成日、更新时间与无 ETA；停止后已停止；提交恢复 ID 不进入 filters；无 pageerror/requestfailed |

冻结合同包含 planning/storage/normalization/source/date_model 和信息覆盖身份版本，Ops request_payload 保存 execution_token、scope_hash、contract_digest、policy_snapshot；plan_snapshot 展示同一上下文。预算只存在 Definition 源码，依赖与默认见§11；没有新 env/DB 开关、Worker/lane 或服务。业务两表无 Ops FK，不保存运行状态。新增 Alembic 182 接实际 head 181，只创建业务凭证及请求预算两表，历史迁移使用固定 DDL，不导入当前 ORM；downgrade 拒绝自动删除凭证。P4 身份 APPLY 必须使用公告执行器同一个 ANNOUNCEMENT_EXECUTION_LOCK，不能仅靠组锁与维护任务并跑。

入口审计：Ops 两个提交 API 和手动维护表单显式支持 resume_from_task_run_id；dispatcher 透传冻结上下文。普通重试、CLI maintain、自动日任务及 workflow 不接受/不自动填该恢复 ID，均创建新观察，不猜最近任务；CLI/自动入口仍用现行时间输入，source filters 不接受恢复意图。已审计 service、TaskRunCommandService 的过滤提取和 workflow builder；通用 SourceConnector.call、Biying、其他 DatasetSourceClient.iter_pages 行为不变，新 bounded 能力只供 Tushare 公告具名策略消费。Definition 日期输入与 freshness/audit 语义没有变化，仍不要求每天存在公告。

本地验收使用任务自有 PostgreSQL 18 临时集群和每测试新建的独立数据库；没有删除、清空或重建任何既有业务表，没有连接 Prod 或正式 Lake。专项 tests/test_anns_d_stream.py、tests/test_bounded_tushare_call.py 与 Ops API 验证上述边界；现有 Definition/resolver/source/normalizer/writer/DAO/Ops/runtime/PDF/架构/codebook 回归通过。前端 31 项测试通过，typecheck、build、check:rules 通过，浏览器公告进度—停止—显式恢复提交用例通过。最终测试数量及检查结果由交付说明记录，不把重复运行相加为独立用例。

性能证据：连续单页生成的 10001 行/6 页，物理读回标题集合完全一致、完成凭证 1；耗时 3.822 秒、最长提交事务 0.198 秒、最大进度回调间隔 0.205 秒，测试父进程峰值 RSS 238.44 MiB。接近 64 MiB 的真实回环 JSON 响应 2000 行解码 0.764 秒，子调用进程峰值 RSS 366.98 MiB，测试父进程（同时运行 HTTP 服务）565.83 MiB。原始证据为 /private/tmp/anns-p2-stream-performance.json 与 /private/tmp/anns-p2-transport-performance.json。64 MiB 是响应体预算，不是 RSS 上限；RSS 含 Python、pytest、解码对象/IPC，且不能外推 Prod 容量或网络耗时。测试捕获的是回调间隔，生产 API/浏览器持续轮询间隔仍由 P3 实际运行验证。

2026-10-02 MCP 只读复核 155162.SH/2023-06-09，start_date=end_date、limit=2000、offset=0、六字段显式请求，仍返回 2 条：name/title/code/date 一致，rec_time 都为空，一条 URL 空、一条有 URL。以原字段进入隔离执行器：源 2、提交合法输入 2、拒绝 0、Raw 物理 1、完成日 1，有 URL 版本保留。不得把 submitted=2 当作物理新增=2；源分页 offset=1 的既有实测见§10，不宣称全站全集已证明完整。

影响面使用 CodeGraph query/impact（IngestionExecutor、DatasetActionResolver、TaskRunIngestionContext、SourceClient、DatasetExecutionPlan），动态 registry/工厂及 API/UI 提交方补当前代码审计；sync/status 最新。没有 foundation→ops 反向依赖、API 名称变更或依赖矩阵变更。仓库外 SQL/id 消费者、真实生产进程资源及发布窗口仍需 P3/P4 核验。

下一阶段 P3：在已批准的代表性范围做目标环境最小真实运行—取消—续跑—读回，对账输入、拒绝、物理集合、页面更新间隔、RSS 和耗时。P4：另行批准结构/身份存量迁移、备份与恢复方案及 APPLY/部署/补录；未获阶段授权前不执行 Prod 写入或大范围同步。PDF 下载后续 M2/M3 仍待前置验收完成。

最终本地检查：一次合并影响面回归 511 项通过（未重复相加）；前端 31 项、Playwright 1 项通过，typecheck/build/check:rules、Definition lint、唯一 Alembic head 182、文档完整性及 diff 空白检查通过。临时 PostgreSQL 集群已停止；没有安装依赖、提交、推送、Prod/Lake/外盘写入。


## 13. Prod 就绪核验与 P4 前置准备（2026-10-02，首份数据库快照13:57北京时间）

当前状态：用户已部署，SSH 只读核实 /opt/goldenshare/goldenshare 的提交为 1ceeef5d2a0763874fdd045378531251ff867d5c；Web、Ops worker、scheduler 均 active。数据库 public.alembic_version 为 20261002_000182，url/rec_time 已可空；迁移两表与完成凭证/请求预算两表存在。group_key 仍可空，按主键首20行的分组均 NULL；迁移 header、业务完成凭证、请求预算查询各自最多5行，均返回0行。当前活动 TaskRun 查询最多20行返回0行，活动公告节点亦0行。此结论是有时点的只读状态，不代表后来不会自动提交任务或已有全量迁移。

因此 P2 代码虽已部署，维护入口仍受 require_identity_ready 门禁限制。执行顺序应按依赖推进：P4 全量存量候选/恢复材料/身份切换 → P3 代表性新同步验收 → 分批历史补录；阶段编号不能替代前置依赖。§12 是部署前本地验收记录，其“未部署”只描述当时状态，不再代表当前 Prod。原14075没有冻结 execution_context，不能直接拿它做新机制的 resume_from_task_run_id；迁移后补历史应创建新观察，续跑只能关联新机制产生且已停止的任务。

### 13.1 只读事实、范围与限制

通过现有 bash scripts/psql-remote.sh/.env.web.local 访问 goldenshare Prod PostgreSQL 16.13；仅目录元数据及指定表投影。每段 BEGIN READ ONLY，查询期限15秒（补核设置5秒），无 DDL/DML；不用临时 Python 客户端另开连接。SSH 核对提交、工具、文件系统与服务状态，不重启、不安装、不修改 Git 配置。最初以SSH当前用户读Git触发 ownership 校验，改用仓库实际所属 goldenshare 用户查询；没有添加 safe.directory。既有 pg_dump/pg_restore 均16.13，与服务器版本匹配。

| 核验项目 | 本次证据 | 解释 |
| --- | --- | --- |
| 日期范围 | ann_date 索引首尾为2020-01-01、2026-09-30 | 当前物理存量时间边界，不证明源站从2020才有公告或每日完整 |
| 主键高水位 | 8091712 | 候选扫描上界，不是行数；主键有空洞 |
| 目录估计 | 7969302 行 | pg_class 估计，不做全表 count 发现规模 |
| 物理大小 | 表2580774912字节，索引1546878976字节 | 约3.844GiB合计，非导出/备份/迁移临时空间总和 |
| 身份门禁 | group_key nullable，首20个id均缺分组 | 新写入将报 identity_migration_required；包括空日 |
| 部署状态 | SHA1ceeef5d，Alembic182，三个服务active | 部署完成与业务就绪必须分开判定 |
| 当前运行 | 活动TaskRun/公告节点0；最近公告任务仅14075、310 | 查询有时点，不永久暂停自动任务 |
| 磁盘 | 根盘可用30709004KiB（约29.29GiB），HDD可用268433316KiB（约256.00GiB） | 根盘已89%使用；不得把所有候选、备份及恢复库放根盘后再测容量 |
| 表空间 | Raw、所有公告索引、映射和凭证均pg_default；HDD表空间另存在 | pg_default不等于已核实的物理盘；当前连接看不到data_directory，实际PGDATA挂载及WAL路径仍需维护前核验 |

只读报告 /private/tmp/anns-prod-readiness-20261002.txt、anns-prod-readiness-detail-20261002.txt；对应 SQL 留在同目录，均未导出公告标题/URL正文。访问目录统计、45条列元数据、6条索引定义、view定义、两条历史公告任务，以及20条id/日期/缺分组布尔样本；其余有界任务/凭证/清单结果为空。表空间16条目录项，不做业务全表扫描。

### 13.2 PLAN 性能前置改造与配置对账

现有离线工具没有生产 APPLY。本轮只改 src/scripts/plan_announcement_identity_migration.py：候选阶段按已有 Definition.storage.reconciliation_batch_rows=500 累积提交，完整分组不拆开；加入下一组会超500时先提交上一批。128个版本的组上限继续来自原storage配置。input阶段原本即500行提交；最终header仍在全部分组校验、最后批提交后冻结，失败草稿没有冻结header。没有新配置、CLI开关、数据库结构或业务合并规则。

本地合成20000行/20000组基准：每组提交耗时7.795秒，批提交1.299秒；完整源摘要与候选manifest摘要完全一致。父进程峰值RSS153.48MiB（包含Python环境），输入5406674字节、最终SQLite17330176字节。SQLite保留临时页的物理容量，不能按候选表逻辑列宽低估文件。基准仅说明本地PLAN开销，不代表Prod读写速度；不能按比例承诺全量ETA。

正向测试含900个普通组、128个非空冲突版本、完全重复与缺URL覆盖样本，跨批仍保留1028/删除2、每次持久提交的变更量不超过500；负向测试129版本失败不冻结且拒绝覆盖已有草稿。专项4项全部通过；离线相关扩大回归20项通过、2项需要隔离PG的用例跳过、7项不在本轮范围。没有修改持久业务数据，因此未重跑P2整套511项或前端；本次只新增本地PLAN测试。CodeGraph query迁移入口、impact RawAnnsD，动态消费者补读script/六字段覆盖contract/专项DAO/迁移181、182/测试；依赖矩阵不变。

### 13.3 完整候选的待批准导出与执行约束

用户要求按步骤推进后，尝试安排全量只读导出，被自动审批拒绝：约809万行的公告title、URL、时间及哈希导出到本地属于大规模数据出域，现有概括授权没有明确覆盖该payload、规模和目的地。命令未执行，不换路径/工具绕过。随后只在本地生成待审阅SQL，没有source.jsonl，没有新迁移token、全量candidate_count/keep_count/delete_count/manifest_digest，也没有Prod写入。

待授权的具体动作：raw_tushare.anns_d，所有上市/债券代码，不按股票池过滤；id从1到8091712，最多8091712行（估计约797万）。显式投影id、row_key_hash、ann_date、ts_code、name、title、url、rec_time，不含raw_payload、其他表或凭据。按主键窗口每批最多2000行，独立短只读事务与15秒查询期限；不用全历史长事务，不以OFFSET扫描。目的地 /private/tmp/anns-p4-prod-plan-20261002/source.jsonl；离线冻结候选及审阅报告放同一目录，已有本机约226.47GiB可用空间。SQL为同目录export.sql，暂不执行。产物含全量业务数据，未经管理员指令不另行上传、传播或删除。

逐批导出不是一致性快照：必须确认维护窗口内公告写入已停、守住同一执行锁，并在候选冻结与APPLY前核验高水位、完整集合及各行源内容/旧hash未变化；一致性无法证明则草稿不能放行。候选需真实统计保留、完全重复删除、覆盖删除及非空冲突，冻结摘要；不能把68行样本删除0推为全量删除0。

APPLY仍待专项实现与验证：先定实际恢复备份路径、表清单、保留期与权限；建议恢复材料放已核验有空间的HDD，不能未经确认就写目录。使用匹配的原生pg_dump/pg_restore，先核验备份和隔离恢复；archive_mode=off，不能假定已有PITR恢复链。申请APPLY前给出实际冻结token/数量/摘要、备份读回/恢复证明、事务预算、预计空间及维护窗口。没有这些材料不物理删除。

迁移每次以完整分组为业务提交/恢复unit（组≤128、批≤500），旧hash和当前内容一致才更新身份/删已证明冗余，applied_at与业务变更同短事务；中断保留已提交组并按冻结清单重放。沿用公告执行try advisory lock，禁止与维护并跑。旧唯一hash索引的中间冲突按§3设计处理，不造临时业务hash、不开放新旧双轨；最终校验保留集合、哈希唯一、group_key全量非空及view投影，再恢复唯一约束和NOT NULL门禁。恢复方案须区分仅更新身份和已经物理删除两种情况。

迁移执行器的Ops意图入口、任务/节点观测及终态、索引建造时的取消/进度设计，必须在APPLY编码前完成0.3.5代码/测试映射；现有离线PLAN不能冒充已经支持这些功能。全量生产APPLY和历史补录尚未授权或执行。

## 14. 存量迁移简化复评（2026-10-02）

本节取代§3/§7/§13对本次正常旧存量默认生成全量删除候选、导出本机及移除唯一索引的执行设想；新同步的六字段身份、保守覆盖合同不变。管理员要求服务器侧处理、不导出到本机。本节为复评方案，迁移代码、生产写入与最终切换均未执行；不是已经通过全量证明。

### 14.1 旧代码能排除什么

核对提交59064b9f（P1前）的 ingestion/row_transforms.py、datasets/definitions/news.py、models/raw/raw_anns_d.py、dao/factory.py和RowKeyHashDAO：旧转换及Definition拒绝缺URL/rec_time，原表两列NOT NULL；title/code/date必填。旧hash为SHA256的分隔串[anns_d,ann_date,ts_code,title,url,rec_time.isoformat()]，不含name；DAO按hash upsert且唯一索引防重复，同键name差异不会各留一条，而是更新同一行。

所以正常旧路径下没有缺URL/时间的残缺行，也没有相同五字段仅name缺失不同的两行。若旧时间统一Asia/Shanghai编码、字段已按旧规则归一，则在同date/code/title组中，不同存量行必有不同非空URL或rec_time；这些都是保守规则要求保留的冲突版本。name可空本身不构成覆盖：覆盖还要求URL和时间相同，而相同五字段已经被旧hash唯一化。之前被拒或同旧hash覆盖掉的数据不在表里，身份迁移不能恢复，须之后重新拉源。

这个结论以旧写入实际一致为前提。旧解析器允许显式时区，hash时间字符串保留该时区，而PostgreSQL按时间点存储；不能从唯一索引直接推导规范化时间后的五字段唯一。人工写入、其他历史写入、未归一字段同样不能凭样本排除。因此逐批校验必须覆盖这些前提，不能直接宣布全表没有冗余。

### 14.2 本轮只读证据

通过既有psql-remote.sh执行READ ONLY，SQL超时15秒、锁超时3秒。三个主键窗口1..2000、4045000..4046999、8089713..8091712各LIMIT2000，实际2000/2000/890，共4890行。数据库端聚合仅返回计数，没有公告字段内容出域。三窗口missing_url、missing_rec_time、missing_name、五字段重复、title/url旧分隔符、已填group_key均0；row_key_hash唯一索引indisunique/indisvalid/indisready均true，无活动anns_d任务。SQL文件/private/tmp/anns-simplification-audit.sql只含查询语句，不含公告数据。样本不是全表证明。

### 14.3 推荐执行范围：只迁移身份，不清理公告

服务器进程使用当前Python身份函数，按主键分页读取，沿用500行短事务预算；不生成JSONL全量副本、不使用本机离线SQLite候选，不默认填充约800万条keep映射。仅更新row_key_hash/group_key，保留id及六业务字段、raw_payload、api_name、fetched_at；不DELETE，不合成/修补业务字段，不提前DROP唯一索引。

每批先核验字段满足旧归一规则、URL/时间非空，并以数据库时间转Asia/Shanghai重构旧公式核对old_hash；新身份直接由当前anns_d_contracts.identity生成。旧公式不符可能是显式时区或其他路径，统一停止并报告有界异常证据，不猜测、不改字段来通过。批次UPDATE必须核对读取时old_hash和实际业务字段，防止读取后变化；新hash唯一索引冲突也回滚当前批并停止，不删行、不移除索引绕过。旧公式校验通过且业务字段已经归一的完整集合，五字段规范相同意味着旧hash相同，唯一索引排除了完全重复和name覆盖冗余；因此不需要对每组生成删除方案。中间新旧摘要若发生索引冲突，同样停下单独评估。

维护期间公告写入关闭，持有现行公告执行串行锁，当前group_key NOT NULL门禁持续关闭新同步。group_key与new_hash同事务写入；group_key非空是已提交身份事实，续跑须验证新hash与实际字段相符后才能跳过，不只信任Ops游标。尚未提交批可重试，已提交批保留。固定高水位和合同指纹，检测范围漂移；进度由已提交量、当前位置和时间表达，取消前后有检查点，观察失败不回滚业务。沿用既有TaskRun观测要求，不新建调度系统或通用迁移平台；具体入口/进度持久化映射仍须在编码前落定。

全部批完成后核验行数不变、ID集合/业务字段不变、全量身份正确、无未迁移行、唯一索引有效及view投影正确，再SET group_key NOT NULL放行。全量核验也在服务器分批进行，摘要/计数和必要有界异常报告可审阅，不返回全量公告内容。并发停止和最终DDL锁时限需要在最小演练中确认。

仍保留服务器侧针对该表的恢复材料及小范围恢复验证：即便不DELETE，全表身份更新也不能没有恢复依据。只备份/验证本次涉及的表，不扩展为整库恢复工程；路径、空间、保留期和恢复权限要在执行前明确。容量/耗时/WAL测量使用小范围身份更新演练，不能用本机SQLite性能推算。

发现异常时只分析异常范围并再评审；不自动升级为全量清洗。后续历史重拉使用已实现的新DAO完成保守覆盖和物理去冗余，迁移不替代补录。旧离线PLAN保留为既有工具，本次不再优化或作为默认生产前置。

### 14.4 剩余验收

编码前补齐服务器身份迁移入口、合同冻结、取消/退出/续跑与现行TaskRun映射；测试正常旧行全保留、name缺失不误删、旧显式时区异常停止、新hash冲突不DROP索引、批次事务回滚、观察失败不回滚业务。服务器小范围演练需证明行数/字段不变、取消续跑和真实耗时/空间，然后再全量身份迁移；完成后进入P3真实同步验收，最后分批补回旧规则拒绝的数据。

### 14.5 精简实现合同（编码前冻结）

入口复用维护动作maintenance.migrate_announcement_identity，GENERAL Worker注册专项executor，不增加Worker/lane。动作不参与调度；现有维护API、手动操作页面、重试、停止与详情页面消费动态catalog；不新增CLI命令，不改变anns_d日常维护合同。单个维护节点内执行有界批次，节点/TaskRun终态由现有dispatcher/worker收尾。

参数审计：execution_mode=CHECK默认，仅CHECK/APPLY；start_id/end_id必填正整数且包含边界；state_path必填服务器绝对路径，保存几KB冻结摘要而非公告；recovery_report_path可空但APPLY必填，指向运营核验的该表备份/恢复报告；expected_state_digest可空但APPLY必填，来自已审阅CHECK结果，按固定JSON键排序计算并复核；finalize默认false，只有APPLY且start_id=1/end_id=真实全表高水位可用。上述均为TaskRun请求意图，持久化ops.task_run.request_payload_json，经catalog/API校验到专项executor；不是env或新增Settings。批次500、事务期限25秒、锁期限5秒继续取Definition.storage；修改预算/实现身份函数会改变冻结指纹，旧CHECK必须重做。服务不创建参数目录，不执行备份命令或自动清理文件。执行仅允许数据库本机loopback或本机绝对路径Unix socket连接，避免本地Worker远程加载Prod公告字段。

CHECK持有公告执行锁，按id升序LIMIT500、每批短READ ONLY事务，验证旧公式/新身份（已经迁移行需验证两字段正确），对id和全部非身份列做流式摘要、统计实际数量并记录全表高水位；每批原子保存不可执行draft统计，完整扫描才原子冻结state_path。冻结文件绑定数据库连接身份（无密码）、代码合同指纹和范围；APPLY重新全量读回摘要相符后才更新，摘要不匹配停止。冻结文件不含公告字段、逐行映射或新增状态机。

APPLY要求服务器恢复报告列明database（与冻结连接身份相同）、table、start_id/end_id、backup_path、backup_sha256、restore_verified_at。校验范围覆盖、备份文件存在及摘要相符，恢复验证由运营真实演练出具报告，不把填写时间当作自动证明恢复成功。文件读取分块检查取消；迁移不替运营执行恢复或删除备份。批次用行锁和读取值条件保护，只有两列UPDATE；事务累计限时，取消检查在批次前后及提交前。已转换行重新计算身份后跳过，恢复无需逐行映射。进度每批更新阶段、当前id、实际完成/总量/时间，CHECK未知总量不伪造百分比；APPLY按已提交身份数量计进度，校验阶段保持完成量不倒退，最终切换前显示暂无法估算ETA。观察失败只告警。

最后再次按批全量核验业务摘要、行数与新身份；保留有效唯一索引。finalize须覆盖全表且无NULL group_key，SET NOT NULL在限时短事务内执行，不自动延长锁/事务；超时停下保留已迁移批。核心代码不依赖Ops，适配器只透传取消/进度，dispatcher既有终态机制保持。没有新增DatasetDefinition/ExecutionPlan合同、数据库迁移或配置默认；真实备份路径/保留期及生产具体执行仍以演练结果和阶段授权为准。

### 14.6 实现与交付账本

精简代码已落地，尚未提交/部署或生产执行：Foundation migration/announcement_identity.py提供服务器本机连接限定、CHECK冻结/复核、逐批身份UPDATE、数据库事实续跑和限时最终切换；Ops announcement_identity_task_executor.py只适配现行TaskRun取消/进度；action_catalog与App worker factory注册GENERAL维护动作。Worker仅针对该迁移动作保留取消/失败时的已提交量，并与活动节点统一终态，其他维护动作不改口径。没有新DDL迁移、DatasetDefinition/ExecutionPlan合同变更、Worker/lane或业务字段修改。

冻结/恢复JSON读取固定上限16KiB，来源为migration模块MAX_METADATA_BYTES，仅read_metadata消费，无运营开关或env配置，新版本生效；文件路径仍为任务意图。备份摘要按1MiB流式读取，批内取消探测节流200ms，批次边界/提交前强制探测；每5秒或备份核验结束报告已核验字节。身份批次用一条Core executemany提交最多500个UPDATE，行锁加原始业务字段/old_hash条件；错误只回报有界id范围和SQLSTATE，不将公告内容嵌入SQL参数异常日志。最终唯一索引重新检查，全表SET NOT NULL继续限时；普通view无需修改，隔离读回验证其行数和新身份。

| 约束 | 实现 | 验证 |
| --- | --- | --- |
| 只更新身份、正常旧存量全保留 | validate_row/old_identity；UPDATE只列group_key/row_key_hash；全业务列含id/fetched_at/raw_payload流式摘要 | name空/不同非空URL/时间、业务字段逐行相同、物理行数相同、view读回 |
| 异常停止、保留索引 | 旧公式/已迁移身份/冻结摘要/高水位/唯一索引核验 | 显式时区、缺值、未归一、SQLSTATE23505、读取后业务漂移、篡改冻结文件、超16KiB元数据 |
| 内存与事务有界 | Definition500行预算、25秒累计批期限/5秒锁限时、短独立读/写事务；1MiB文件块 | 实测40写批且每批≤500；事务失败/提交前取消整批回滚 |
| 持久化续跑及观察隔离 | 两身份列同事务提交，重算验证后跳过已完成行；独立TaskRun观察 | 500行提交后取消、SystemExit及实际os._exit(17)后新进程续跑、重放、观察故障不回滚 |
| 正式入口与终态 | 维护API→现有dispatcher→GENERAL Worker；新Ops适配器及限定worker收尾 | API CHECK真实提交、成功/失败/取消TaskRun与节点一致、既有Ops/API/架构回归 |
| 恢复材料和最终切换 | 报告绑定数据库与范围，备份文件摘要复核；只有完整范围可finalize | 隔离pg_dump/pg_restore新库演练及原字段读回、缺报告/错摘要/部分范围切换拒绝 |

验证使用既有PostgreSQL18任务专属socket/private/tmp/anns-p1-pg-socket-20261002，每例新建隔离数据库，不触及正式本地库或Prod，不安装依赖。专项增加真实进程强制退出和原生备份恢复；性能测量的合成恢复资料明确只用于计时，不充当生产恢复证明。相关API/运行时/架构回归及ingestion-lint-definitions、docs integrity、diff检查通过，CodeGraph explore核验dispatcher/worker/进度适配器影响面，补充当前API/query/frontend通用消费者源码，sync/status正常。

隔离2万行性能：CHECK0.604秒；APPLY加前后读回及最终切换2.044秒；40个写批、最大500行；进度报告最大间隔0.031秒；整个基准进程峰值RSS192,413,696字节（含测试/应用导入），WAL生成22,031,568字节，表加索引19,046,400字节。冻结文件509字节，没有逐行映射或公告副本。报告/private/tmp/anns-identity-performance-20261002/performance.json。合成记录字段长度与Prod不同，不能线性承诺Prod耗时/峰值WAL/磁盘空间。

本轮Prod只读补核：原生PG16的data_directory=/var/lib/postgresql/16/main，base和pg_wal没有重定向，落系统盘；该盘可用31,318,720KiB约29.87GiB、89%使用。/data/disk可用268,432,956KiB约256GiB，但root:root/755，goldenshare无目录创建权限。运行Worker按GOLDENSHARE_ENV_FILE与当前Settings文件优先规则解析/etc/goldenshare/web.env，数据库host127.0.0.1、port5432、库goldenshare；仅输出位置/host/port/库名，不输出凭据。没有改变配置、创建服务器文件或写生产数据。

下一步部署Web和GENERAL Worker（catalog与executor需同版），准备服务器/data/disk/goldenshare/anns_identity_migration/20261002工作目录及goldenshare权限，在该目录保存冻结小文件和该表原生恢复材料。该路径是具体演练提案，尚未创建、未备份；保留期/恢复权限在执行前确认，禁止自动清理。先CHECK id1..2000、review state_digest；完成针对raw_tushare.anns_d的服务器备份/隔离恢复验证报告后，小范围APPLY finalize=false，进行运行—取消—续跑—读回及实际WAL/空间测量。部署和生产具体演练尚未执行，不把本地结果当Prod通过。小范围通过后再CHECK冻结全表、明确全量空间/恢复范围和阶段授权，最终APPLY/finalize；之后进入P3源同步验收，再补历史拒绝数据。


### 14.7 2026-10-02 Prod服务器演练记录

管理员部署后授权继续推进。SSH核实Prod提交5875061171b68237d4975eba67c02b2dc4e452d1包含cb4f2216，Web与GENERAL Worker均于20:57重启，服务器Git无改动。主键高水位8091712；有界只读查询确认id1..2000共2000条且group_key均NULL，初始无公告执行冲突。沿用现有Worker和TaskRun服务，不创建新Worker、不重启其他服务。

服务器专用目录/data/disk/goldenshare/anns_identity_migration/20261002由goldenshare创建。CHECK任务14228成功，count=2000、migrated=0，冻结check-1-2000.json：state_digest=c5f93a8edc5f01cc65590907713d3654b48f949cc6c146c691cc1a7f58fd97c6，business_digest=6b808556f13f9f0eba51c9e85f5d703a9e87e973f3c7b81529a2abe6ede2fabd。每批≤500，业务内容没有传回本机。

服务器PG16.13原生pg_dump仅备份raw_tushare.anns_d，--format=custom/--no-owner/--no-acl/--lock-wait-timeout=5s；备份anns_d-before.dump为551823900字节，SHA256=ab6b9caf4176553fbe0d4e33a52c02ab95bb1fca87904d39738aa6b1f56ad771。原生pg_restore --exit-on-error完整恢复到新建独立库anns_identity_restore_20261002_2102，不覆盖Prod；恢复成功退出，恢复库精确7969302行，原唯一索引有效，id1..2000全部非身份业务字段摘要与冻结结果一致。全表恢复成功不等于已对全表做逐字段摘要对账。

自动审批拒绝验证库GRANT SELECT TO PUBLIC，因扩大访问面；该命令未执行。随后采用既有postgres管理员权限只读验证，无新增授权。真实恢复报告recovery-report.json和WAL基线pilot-before.json均留在服务器；恢复库及备份保留，不执行自动清理。21:08恢复后系统盘可用57010480KiB约54.37GiB、HDD238219032KiB约227.18GiB；恢复库约3586MiB。不是全量APPLY空间峰值承诺。

小范围APPLY14230绑定上述冻结摘要/真实恢复报告、finalize=false。等待原GENERAL Worker收盘维护14229自然结束后，于500行提交观察后经TaskRunCommandService.request_cancel取消，任务与唯一节点均canceled/rows_saved=500；物理扫描确认migrated=500、全部2000行业务摘要仍与冻结相同。新任务14231同参数续跑，跳过已提交500条、更新余下1500条，任务/节点均success/rows_saved=2000；该计数是范围内已迁移总量，并非本次新增量。同参数幂等重放14232成功，重新读回count=migrated=2000、业务摘要不变、唯一索引有效，group_key仍可空，未finalize。四任务均经过正式GENERAL Worker，不是测试注入或独立执行器冒充生产入口。

服务器pilot-final-readback.json保存终态与读回证据。CHECK14228实际0.448秒；取消APPLY14230约3.818秒；续跑14231约3.283秒；重放14232约2.431秒。21:13 Worker当前RSS448900KiB、生命周期VmHWM531972KiB，包含先前收盘工作流，不是迁移独占峰值；WAL基线至最终读回差363934792字节，包含排队期间其他任务写入，不得据此推算公告每行WAL。目标表加索引4128038912字节。

全表只读CHECK任务14233成功，范围1..8091712、state_path=check-full.json，任务/节点均success、rows_fetched=7969302、rows_saved=0。开始21:13:48.692924，结束21:37:08.849952，耗时1400.157秒（23分20秒）。每批500短只读事务，总count=7969302、migrated=2000，余下7967302条待迁移；旧公式/归一化/已迁移新身份全部通过，无异常停止。冻结文件473字节，state_digest=47f3db258026caf447ce9d3d5ebd69b8055bf92e1309c2effcba47627cd1f923，business_digest=473b2fa7ba8158c3501b5288aeb07e17d7d3f6218adcaf6a6b2a1118e3f5f4a2。高水位8091712未变，唯一索引仍unique/valid/ready。每30秒读取单个TaskRun与/proc，所采样RSS始终448900KiB，生命周期VmHWM531972KiB未增加；这不是高频瞬时内存采样。

21:37只读空间复核：系统盘56940048KiB约54.30GiB、HDD238219012KiB约227.18GiB可用。备份和恢复库保留，不自动删除；恢复报告705字节。全量APPLY至少含前后两遍全表校验，按本次CHECK耗时推测仅校验就约47分钟，此外有备份摘要及业务UPDATE开销，不能承诺总耗时或WAL峰值。小范围WAL混入其他写入，不能线性估计；以现行取消/批次持久化能力支持执行时持续观察空间和进度，不能把空闲容量当完整峰值证明。

待放行的具体全量意图：execution_mode=APPLY，start_id=1，end_id=8091712，state_path=/data/disk/goldenshare/anns_identity_migration/20261002/check-full.json，expected_state_digest=47f3db258026caf447ce9d3d5ebd69b8055bf92e1309c2effcba47627cd1f923，recovery_report_path=/data/disk/goldenshare/anns_identity_migration/20261002/recovery-report.json，finalize=true。仅更新两身份列，保留已迁移2000条与全部业务内容/id/唯一索引；最后完整读回通过后限时SET NOT NULL。未创建全量APPLY任务，也未执行最终DDL或源同步；按§14.6另行取得此完整范围阶段放行，再进入P3代表性同步，不能直接开启历史补录。


### 14.8 迁移性能复评及待确认优化（2026-10-02）

管理员质疑约1.6万写批的执行成本，本节只记录源码审计、服务器只读计时及候选调整；尚未修改迁移代码、预算或冻结文件，也未启动全量APPLY。CodeGraph CLI query AnnouncementIdentityMigration/TaskRunIngestionContext、impact AnnouncementIdentityMigration定位迁移、Ops适配与测试影响面，再核对当前源码；不修改通用TaskRun行为、日常anns_d同步批次、Worker/lane、CLI/API或子系统依赖方向。

现有代码成本：CHECK每500行atomic_json草稿，fsync文件及父目录；每批emit触发独立TaskRun/节点观察事务，多次强制取消探测又开启独立读事务。APPLY两次_scan没有draft落盘，因此§14.7直接按23分20秒CHECK乘二得到47分钟只能视为此前粗估，不能作为同路径实测。每行validate_row先调用_anns_d_row_transform（已经生成身份），又调用contracts.identity；未迁移行old_identity被重复调用。写批调用Core executemany，提交最多500个带条件UPDATE，并不是一条集合UPDATE。相同500行预算同时取自日常Definition，不能为迁移提速直接改Definition而波及日常同步。

只读计时通过SSH，在已恢复验证库anns_identity_restore_20261002_2102读取raw_tushare.anns_d，白名单为当前TABLE字段，用于原校验/流式摘要；三个PK窗口1..20000、4000001..4020000、8000001..8020000各20000行，每批500短READ ONLY事务。没有Prod公告写入、没有内容导出、没有新增授权或依赖。cProfile先用于定位调用，再单独运行无profile、无草稿/观察写入且取消callback为no-op的原_scan：分别2.283/2.069/2.209秒，约8759/9666/9054行每秒。小样本有缓存、不同连接身份及省略控制开销，不能承诺整表同速；线性外推仅两次读回约27.5—30.3分钟，不包含UPDATE、观察/取消事务、备份摘要、负载及最终DDL。没有测得纯业务写批平均耗时，故完整APPLY暂无可信总ETA。

约15935个实际写批的敏感性示例（是假设，不是实测）：每批0.1/0.3/1秒，仅写阶段即26.6/79.7/265.6分钟，另加前后读回；不能拿含固定备份核验的小范围3秒直接乘约4000倍承诺生产工期。批次5000候选对应全表1594个读取批，剩余7967302行也最多1594个写批；行级处理量不变，减少的是事务/控制/SQL调度次数。

建议确认后统一实施并同步修改§14.5：

1. 复用归一化器已生成的新身份；旧公式每行只计算一次，保持全部比较、NULL/时区/异常规则及业务摘要不变。
2. 用有界VALUES驱动的一条UPDATE FROM代替每行executemany；保留两列修改、FOR UPDATE、旧身份及原始业务字段匹配、受影响行数断言、唯一索引、整批回滚和错误不泄漏内容。
3. 迁移独立批次候选5000，不修改日常Definition的500。5000不是已验证最终值，须在既有恢复库真实样本证明内存、SQL参数量、吞吐及25秒累计期限；若不达标，先复评而非静默延长事务期限。
4. 草稿与Ops进度按最多5秒间隔保存，阶段转换、完成、取消及失败边界强制更新；实际完成量只能来自已提交事实，业务每批仍独立提交并检查取消，页面更新继续低于30秒门禁。CHECK草稿不是可执行checkpoint，完整校验才冻结。

候选预算审计：IDENTITY_MIGRATION_BATCH_ROWS=5000、IDENTITY_MIGRATION_REPORT_INTERVAL_SECONDS=5拟为migration模块具名代码预算，只用于本次迁移，不新增env/Settings/数据库/运营参数；前者供迁移读取/写入unit，后者供草稿/进度节流，Ops适配只消费节流后的观察事件；发布后生效，合同指纹须绑定两预算。运维通过阶段/最后id/已提交量/更新时间观察，不开放绕过校验的开关。以上名称和值仍待方案确认及真实验收，当前实现保持500/逐批观察。

验收至少比较原、新校验所得新身份及业务摘要一致；集合更新保持原字段与id、行数及唯一索引；一批失败/取消整批回滚、进程退出/续跑/重放、观察失败隔离、单调进度和终态一致；另外证明多批期间进度间隔≤5秒、非终态草稿不可APPLY、SQL参数/内存有界、25秒期限不放宽。修改会改变现有冻结合同指纹，需要用新版本重新CHECK，不直接拿当前check-full.json授权新算法；既有服务器备份/恢复材料保留。全量APPLY继续待独立阶段放行。
