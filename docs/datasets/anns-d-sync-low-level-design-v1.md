# 上市公司公告同步完善 LLD v1

更新时间：2026-10-02。状态：P1/P2 源码与本地隔离验收完成；P3/P4 尚未执行，Prod 未变更。物理去冗余按用户已确认的保守覆盖规则实施。[技术方案](/Users/congming/github/goldenshare/docs/datasets/anns-d-sync-technical-plan-v1.md)定义业务原则，本文件是实施与验收约束。按[开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)填写专项设计；0.3.5 摘要同步回原维护说明。

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
