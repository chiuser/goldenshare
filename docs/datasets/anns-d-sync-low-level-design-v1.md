# 上市公司公告同步完善 LLD v1

更新时间：2026-10-02。状态：P0 设计文档；全部新字段、策略、表与调用尚未实现。[技术方案](/Users/congming/github/goldenshare/docs/datasets/anns-d-sync-technical-plan-v1.md)定义业务原则，本文件是实施与验收约束。按[开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)填写专项设计；0.3.5 摘要同步回原维护说明。

## 1. 目标合同及文件影响面

| 当前实现位置 | 后续改动 | 不得发生 |
| --- | --- | --- |
| src/foundation/datasets/definitions/news.py、models.py | anns_d 必填、按日 unit、具名执行/写入策略 | executor 内按 dataset_key 硬编码 |
| src/foundation/ingestion/row_transforms.py、normalizer.py | 可空时间/URL、类型化六字段指纹、质量样本 | 用 now() 补造时间、仅按键拒绝 |
| src/foundation/ingestion/unit_planner.py、request_builders.py | 日窗口规划、仅 start/end 映射 | Ops 展开日期、改成必须每日有数据 |
| src/foundation/ingestion/executor.py、source_client.py | 有界分页处理、取消、预算、业务凭证回调 | buffer_all；未经语义审计套用 staged_stream |
| src/foundation/models/raw/raw_anns_d.py、core_serving_light/anns_d.py、dao/factory.py | 源记录证据、有效投影、专项 DAO | 修改 RowKeyHashDAO 影响其他数据集 |
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

算法处理一批：归一化→按 source fingerprint 排除完全重复→按 group_key 排序分组→锁住组→读取该组全部不同版本（LIMIT 129）→超过128则报 group_version_limit_exceeded，不自动丢行→核对真实组字段→加入新源版本→计算全部极大元→更新 current/covered 指向→原子提交。处理量最多一个源页及500写入行、一个128版本候选组，不全表/全日期加载。多个极大元覆盖同一行时 covered_by_id 指向指纹字典序最小的极大元，直接指向有效行，不形成链或环。

重要性质：相同源版本重放无新增；集合相同则有效输出与到达顺序、分页、分批无关；非空冲突不丢失；旧完整版本不能被后来的残缺版本降级。增加信息可能让有效行数量减少，这是集合变化，不是业务进度倒退。

## 3. 物理与读取模型

raw_tushare.anns_d 保留 id、现有六字段、api_name/fetched_at/raw_payload。设计新增 group_key(char64)、is_current(boolean)、covered_by_id(bigint nullable，自引用FK)。url/rec_time 改 nullable；row_key_hash 唯一但公式迁移；group_key 有普通索引，(group_key,is_current)覆盖查候选和有效版本，covered_by_id 用于追溯。DDL 具体索引须用代表性 EXPLAIN 和体积测算确认后提交，不在 P0 执行。

core_serving_light.anns_d 仍是同名普通视图，沿用现有源字段及source/fetched_at，只返回 is_current=true。Raw 仍保存被覆盖证据，不给普通消费者返回冗余版。原始证据查询必须显式指定 Raw，不把证据当有效公告。内容不同的源行 ID 不合并、删除或复用；完全重复已有旧行的迁移也先标为非有效并关联代表，不删除。

存量身份迁移设计使用 raw_tushare.anns_d_identity_migration 候选/恢复映射表：migration_token UUID、raw_id bigint、old_hash/new_hash/group_key char64、old_is_current boolean nullable、old_covered_by_id bigint nullable、candidate_is_current boolean、candidate_covered_by_id bigint nullable、applied_at timestamptz nullable；唯一(migration_token,raw_id)。映射按id分页生成，覆盖现有所有行，校验count/缺漏、实际六字段和新hash唯一性后冻结；冻结标记、合同digest、high_water_id存同迁移header记录，冻结后不可改候选。迁移阶段禁止并发业务写，按500行短事务更新业务行及applied_at；恢复按映射倒序分批还原，不靠进程游标。DDL确切迁移版本在P1检查真实head后生成。

如果新hash不唯一（包含等价时间规范化等情况），候选验证即失败，不进入APPLY，不自动删除、搬走或给重复证据造假hash。这是清楚的拒绝边界；发生真实碰撞时重新给出具体受影响raw_id与另行清理设计，不能用本P0授权隐式处理。即使SHA碰撞但六字段不同也失败。正常无碰撞路径保留所有原id并标记覆盖，不需要清空或重建原表。当前唯一旧hash可能已压缩部分name差异，不能从旧库恢复被覆盖信息，需重拉源。

业务完成凭证设计表 raw_tushare.anns_d_sync_unit：execution_token UUID、contract_digest char64、scope_hash char64、ann_date date、attempt_token UUID、terminal_page_number、terminal_offset、terminal_rows、rows_observed、rows_committed、reason_counts JSONB、completed_at timestamptz。唯一(execution_token,contract_digest,scope_hash,ann_date)。只保存完整完成事实，无 queued/running/failed 状态，无 Ops FK，不成为 TaskRun 替代。execution_token由组合适配层生成并透传，foundation当作不透明token。完成凭证随最后业务批提交；空日短页仍提交凭证。重试不删除凭证或原业务行。

## 4. 日窗口、事务、预算与取消

resolver冻结升序日列表及scope_hash（日期范围、代码过滤、数据集/合并合同指纹），point=1，range=end-start+1；无日期入口仍不支持。date_model 的自然日输入、not_applicable freshness、ann_date观测三层保持分离。规划超3,660天立即拒绝，不能先运行再扩计划。

一页源返回最多2,000，分最多500行批，每批事务包括源行及组投影更新；页中断保留此前已提交批，页不得标完成。最后短页的最后批与 unit 凭证原子提交。空页单独短事务写完成凭证。整日不持有数据库事务。未完成日已提交批可见，因此有效视图是当前已观察记录的有效集合，不承诺未完成日是源端完整快照；完成凭证另表表达观察窗口完成。UI/下载不得把已有有效行误报整日同步完成。HTTP请求前关闭先前SQL事务，避免此前14075的长idle-in-transaction。

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

只有同冻结执行execution_token、scope_hash、contract_digest才允许跳过有完成凭证的日；unfinished日offset从0。新维护任务即使日期相同也是新观察，不能跨任务永久跳过。续跑关联只由运营明确表达，Ops保存意图并由resolver核验来源范围/过滤/digest；自动日任务不默认关联历史任务。恢复意图目标schema：Ops维护提交请求顶层可选resume_from_task_run_id（正整数、默认NULL），不放进源filters或Tushare请求。Ops核验原任务属于anns_d.maintain、已停止执行、调用方具有现行运营权限，读取原execution_token并将范围/过滤/digest交resolver校验；不匹配拒绝，不支持running任务并行恢复。新TaskRun独立保存恢复意图及来源任务ID，共享业务execution_token，原TaskRun历史不改。API、手动表单、CLI、自动workflow及所有提交方在P2迁移审计中同步支持或显式省略；当前代码尚无此能力，不以文档声称已可使用。

进度阶段：planning、fetching、persisting、reconciling、completed/canceled/failed。展示当前日期、页号、源返回量、已提交输入量、新增源版本、完全重复、残缺覆盖、冲突组、无URL/无时间、质量告警、完成日/总日/百分比、最近更新时间。百分比按完成日凭证；进行中的日显示具体页/量；总源行未知，不报源行百分比。ETA显示暂无法估算，达到代表性样本后再评估，不能预设倒计时。

计数分层：每次源返回行必须归入已提交输入/未提交输入/真拒绝；重复重放的提交输入是处理量，不是新增公告。新增源版本+已存在版本可解释已提交合法输入。当前有效公告数量是读回状态，可能下降，不能作为单调业务进度。冲突是组级告警不叠加到行数等式；缺URL/时间是可重叠质量计数。P3对账源输入、源版本与有效输出三个口径，不用一个rows_saved混算。

Ops观察更新独立session；提交后报告，失败只告警不回滚业务。每页开始、结束、每批后有业务进度；请求最长25秒，确保30秒内可见更新。runtime在成功/失败/取消同事务更新TaskRun和当前节点终态；若观察库不可用，保留业务完成凭证并由既有恢复路径修复，不假造已写终态。关闭进程后恢复当前状态不是自动续跑生产业务，恢复执行仍需要明确意图。

reason code设计：quality.invalid_rec_time、quality.missing_url、quality.missing_rec_time、merge.identical、merge.covered、merge.conflicting_attributes、anns_d.group_version_limit_exceeded、anns_d.request_budget_exceeded、anns_d.response_size_exceeded、anns_d.identity_collision、anns_d.dataset_busy。新增时同步codebook，quality/merge不等于rejected；必填缺失沿用已有code。最终拼写和API统计映射P1/P2实现前冻结，不能只有文档存在。

## 7. 存量迁移、发布和恢复

先检查真实Alembic head，新增迁移只能接真实head。P1演练生成按raw_id分页的映射候选和只读报告，含当前总量、新指纹重复、名称差异、组版本上限、预计有效量/覆盖量、索引大小、迁移耗时及冲突样本。计划覆盖当前所有anns_d数据，不只14075日期范围。保存候选后校验并冻结才可APPLY；候选路径、物理表清单、空间、逐批恢复凭证在演练中固定，不先写Prod再补。

部署按“停止领取公告任务且等待旧任务退出→备份/恢复方案与权限确认→增量结构→分批身份/组投影迁移→校验→切换六字段写入及有效视图→适配消费者→代表性验收→恢复领取”。迁移与业务写不能使用两套身份同时运行。维护窗口内禁止新脚本消费未完成的有效投影，不新建公共开关。保留id，非有效标记不删除源证据。

恢复：DDL允许空值后旧程序仍可能错误拒绝，不能退回旧逻辑当作成功回滚。新NULL数据存在时不收紧NOT NULL；身份迁移出错保留批次候选与凭证、停止新写，按获准映射恢复，不能truncate重建或恢复旧哈希双轨写入。迁移候选/恢复表已在§3明确；新hash非唯一时拒绝APPLY，不能在执行中临时扩大表清单或删除行。

代表性生产授权另行取得。历史补录选择日期范围/代码、预算和执行token，先小范围运行—取消—续跑—读回，再分批历史范围。14075历史记录保持原结论，不改计数伪装本次成功。拒绝样本有限，补历史重新请求源；源变动可能使最终数量不同。

## 8. 硬要求追溯与测试矩阵

| ID / 硬口径 | 代码点 | 正向 / 负向验证（尚未执行） |
| --- | --- | --- |
| A01 缺url/时间可保存 | Definition、transform、ORM/DDL | 各缺、都缺；不造日期/链接 |
| A02 完整覆盖残缺 | 专项DAO、有效view | 155162.SH样本；日期/标题不同不得合并 |
| A03 非空冲突保留 | 覆盖算法 | 两URL、两时间、两名称；不能按分数选一条 |
| A04 不合成源行 | payload与覆盖算法 | 互补残缺保留两条；完整C到来再覆盖 |
| A05 顺序与跨页无关 | group锁、批提交、指纹 | 枚举输入排列/分页切分，输出相同；重放无新增 |
| A06 稳定证据与单一身份 | hash/id/covered、迁移 | id保持、覆盖直接指极大元；碰撞不能覆盖 |
| A07 日窗口不等于完整性桶 | resolver/builder、freshness消费 | point/range、空日成功；不要求每天公告 |
| A08 内存/请求有界 | executor/connector/预算DAO | 大量页RSS稳定；每个阈值超限报失败而非截断成功 |
| A09 取消退出续跑 | 业务凭证、runtime | 第500行后/最后页前/commit后崩溃；保留提交、未完成重放 |
| A10 观察独立与终态 | 适配层TaskRun/node | 状态写失败不回滚、恢复读回、终态一致 |
| A11 进度真实 | progress/API/frontend | 30秒更新、单调完成日、有效数减少不当失败 |
| A12 消费者不读冗余 | view、PDF source/ledger | covered不枚举、NULL不崩、缺URL跳过、代表换ID不重复下载 |
| A13 新观察不误跳 | resolver/恢复输入 | 同计划跳完成日；新任务同范围仍请求；digest错拒续跑 |
| A14 源代码不限股票池 | transform/filters | S1649.SZ和155162.SH可存；非法必填仍拒 |

本地测试计划：现有Definition、resolver、source_client、normalizer、writer、row_key_hash DAO、Ops action/API与架构/codebook门禁；新增anns覆盖DAO与业务凭证事务故障测试；PDF CLI专项。UI如变更必须做真实浏览器取消/续跑和进度可见性验证。测试路径存在性先确认，不安装包或隐式同步依赖。

最小真实验收：155162.SH/2023-06-09两源版本→Raw证据两条、有效一条；S1649.SZ/2024-12-31缺时间有URL正常保存；选第二页真实样本校验源参数/分页；代表性多页范围执行取消续跑并按指纹集合读回，峰值RSS、API更新间隔、调用超时及数据库事务长度记录到原维护说明。覆盖源/normalize/commit/raw/current计数与每种理由；没有可信全集基准时不得宣称源站全集完整。

## 9. P0完成判定与未执行项

P0只验收事实核验、决策表、影响面、配置设计、0.3.5、迁移边界和测试计划；本轮文档检查结果由交付消息记录。P1实际身份迁移、P2源调用/恢复输入配置消费者审计与性能验证、P3真实写入验收、P4生产迁移全部未执行。待后续具体化的是实现/部署证据，不把未实施设计写成已支持功能。


### 2026-10-02 P0验证记录

- python3 scripts/check_docs_integrity.py：绝对链接、DS_Store、Tushare索引三组通过。
- git diff --check：通过；另逐文件检查本轮6份文档含新增未跟踪文件的尾随空白及末尾换行，均通过。
- 临时独立规范模型检查：7个组内覆盖场景，22种输入排列及各自重复输入检查通过。模型只实现§2偏序，未调用生产DAO，不代表源码测试、性能验证或跨组数据库验收。
- 核对技术方案、LLD、原维护说明、PDF两文档及主索引：现行/目标/历史证据分开；旧buffer_all和必填行为保留为现行说明；原PDF M1不升级为新合同已兼容。
- P0文档范围完成；P1—P4及PDF后续阶段均未执行。没有源码、迁移、配置、Prod、Lake或外盘变更；未提交或推送。
