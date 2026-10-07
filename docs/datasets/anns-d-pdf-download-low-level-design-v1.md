# 上市公司公告 PDF 本地归档 LLD v1

更新时间：2026-10-07。状态：Q3 PG执行/CLI切换已实现并进行隔离验收；当前合同与命令见本文 §19，[详细报告](../../reports/wealth_data_center_q3_acceptance_20261007.md)。§1—§18 保留此前 SQLite/DC 阶段历史，其中台账路径、schema1/2/3运行时升级和不依赖PG等说明已被§19替代，不再作为当前命令操作指南。正式迁移和统一启用属于 Q4，尚未执行，不能提前部署开发版。

§1—§16保留2026-10-05及更早阶段当时的实现和验收记录：DG schema2读者/五URL归档/台账维护，以及Prod M0—M3历史。独立旧验收台账曾升级到2，不代表此次已迁移到3。§17为网页技术目标引用。[技术方案](anns-d-pdf-download-technical-plan-v1.md)说明后续范围。

## 1. 改动范围、依据与依赖

旧 Prod 入口 `main → Volume.open → configured_database → Ledger → Source → execute`，已被替换。2026-10-05当时入口为 `main → 输出卷门禁 → DG 来源卷/依赖预检 → Ledger(schema 2) → Source.iter_days → 封存枚举 → 原文件下载/恢复流程`。已完成以下代码与测试迁移；后续五 URL 真实归档范围及结果见 §15。

| 位置 | 迁移目标与影响面 |
| --- | --- |
| `src/scripts/download_announcements.py` | 移除 Settings/DB 建连与 id 游标；逐日/逐批落账、封存检查和 Source 关闭；移除逐文件 has_artifact |
| `src/scripts/announcement_download/source.py` | 单一 DG Raw reader、六字段校验、固定 fd、批迭代、日指纹及可取消 DuckDB；不保留 PG reader |
| `src/scripts/announcement_download/core.py` | 集中 source 默认策略及日期下载投影/源指纹所需类型；旧文件 identity 算法不变 |
| `src/scripts/announcement_download/volume.py` | 复用已审计的卷识别与句柄校验；源卷使用只读路径，不能复用输出写探针或建目录 |
| `src/scripts/announcement_download/ledger.py` | schema 2 原子迁移、DG 来源映射、日输入事实、封存门禁与增量计数 |
| `src/scripts/announcement_download/files.py`、`http.py` | 保留安全文件/HTTP 协议；复用已有 artifact_key、路径、prepared 与冷却 |
| `tests/test_announcement_download_cli.py` 及同域专项测试 | 一次迁移 Source fixtures、旧 DB/id 断言及所有账本消费者；增加独立 Parquet/旧账本金样本 |

来源以 [DG 六字段合同](../../lake_console/orchestrator/src/orchestrator/defs/anns_d_contract.py)、[paths](../../lake_console/orchestrator/src/orchestrator/defs/paths.py)、[promote_day](../../lake_console/orchestrator/src/orchestrator/defs/anns_d_io.py) 为依据。consumer 不 import orchestrator；字段序列/版本一致性由跨域合同测试核验，不创建旁路 DatasetDefinition 或改变数据集时间模型。

维持工具目录归属，不新增业务子系统，不改 Foundation/Ops/Biz/App/QTF 依赖矩阵。不会在工具中引用 Dagster runtime、staging 锁 helper、PG/CH 或旧 Lake/Kopia 实现。已审计 Foundation `StockMinsLakeReader`：它读取 Gold 分钟数据、按分页查询，并不提供公告所需 fd 固定/逐日流式语义，不能仅因使用 DuckDB 就复用它。

使用已有 httpx、标准库和根项目 local-lake DuckDB 可选依赖。缺 DuckDB 时启动明确失败，不能隐式安装、同步依赖或下载扩展。删除工具的 SQLAlchemy/psycopg 使用不表示移除仓库其他功能的共享依赖。

## 2. 参数与配置项审计

所有默认值由 `DownloadOptions`/`DownloadPolicy` 和唯一 source 路径工厂提供，禁止散落多套默认值。新项在实现前已按本表审计，本轮已集中落地。

| 名称 | 默认与来源/持久化 | 消费者、作用范围与依赖 | 生效、可见性与测试 |
| --- | --- | --- | --- |
| --start-date / --end-date | 必填 ISO 日期，end≥start；CLI，runs 保存实际值 | source 自然日闭区间、runner、progress | 每次启动；边界/空日/缺日/非法参数 |
| --interval-seconds | 5.0，有限非负，可小数/0；CLI，runs 保存 | HTTP/limiter/retry/redirect；不能缩短已有 cooldown | 下次启动；时间戳/fake clock/重启测试 |
| --output-root | /Volumes/datasource/announcements；CLI，archive 卷身份/相对路径 | 输出 volume、ledger、files | 启动；外卷/不同输出卷/禁止 Lake 路径 |
| DG source 根（固定来源，不新增开关） | /Volumes/datasource/data_lake；唯一 source 工厂，source_scope/runs 记录规范来源 | source 路径仅 raw/tushare/anns_d；依据 DG paths | 启动；旧 config/env 不能覆盖，缺路径无 fallback |
| 账本路径（沿用自动派生） | ~/Library/Application Support/Goldenshare/announcement-download/<归档身份>/downloads.sqlite | ledger；归档身份仍是输出卷 UUID+卷内相对目录 | 启动；同卷重挂载复用、不同卷隔离 |
| source_contract_version | DG ANNOUNCEMENT_VERSION 当前为 1；source 固定合同，scope/runs 持久化，日事实通过 run_id 关联 | source 六字段/schema；新记录 key 与旧 PG 来源隔离 | 合同一致性测试；字段顺序漂移启动阻断，Raw 无版本列不能运行时猜版本 |
| batch_size | 500；原 Policy 默认，替换 DB 消费者为 source/ledger | fetchmany/单批提交、取消边界；日余批可小于 500 | 启动；501+跨批反例、禁止 fetchall/OFFSET |
| source_query_timeout_seconds | 15；替换旧 db_timeout_ms，集中 Policy；runs 策略摘要 | 每个 DuckDB 阻塞读取调用的超时/interrupt；不含暂停落账时间 | 每调用；超时/取消/线程回收/安全关闭 |
| source_memory_limit / source_threads | 256 MiB / 1；集中 Policy，runs 策略摘要 | 单一 source DuckDB，内存用尽阻断；不声明等于 RSS | 启动；低内存反例、真实最大日 profiling |
| source spill/扩展策略 | 禁止 spill（max_temp_directory_size=0）、禁自动安装/加载扩展；唯一连接工厂 | source，仅本地 Parquet；不能写正式/staging/系统缓存 | 连接建立；trace 无临时文件/扩展网络 |
| GOLDENSHARE_ENV_FILE / DATABASE_URL | 从此工具移除，不加载/不消费；仓库其他模块不变 | 无运行期消费者，不保存旧连接凭据 | 启动；缺 env 也可读 DG，设 PG env 也零连接 |

其他现有 Policy 保持：串行 1、diskutil 超时 10s、HTTP 64 KiB 块、PDF 上限 512 MiB、安全余量 1 GiB；connect/read/write/pool 超时 10/15/15/5s，正文期限 600s；尝试 3 次、最多 5 跳重定向、退避 30/60/120s、basename 200 UTF-8 字节；进度 ≤5s、等待分片 ≤0.5s。消费者仍为 volume/files/http/Control/ledger，原正反例继续回归。

配置不存在 DG daemon/PG/CH 启动依赖，也不引入每日同步参数。source 预算与 batch/取消相互约束；超预算停止并报告，不自动扩大参数。台账可读参数摘要、终端显示脱敏来源和实际日期/间隔；维护查询入口在后续阶段，不由本次另加 CLI。

## 3. 启动、外盘与权限门禁

1. 校验原 CLI 参数；失败不读取 Raw、不打开账本、不建目录。
2. 先验证输出目标真实外置卷、UUID、Mounted/Writable 和 APFS physical store。排除内部卷、映像、符号链接与 Lake/staging/退役目录；固定目录 fd 后才创建归档子目录、执行自身可写探针及空间/fsync 检查。不能 mkdir 挂载点。
3. 只读识别 DG 来源的 datasource 卷，固定 UUID/设备/目录 fd，逐层 O_NOFOLLOW 查找正式源路径；来源不存在或不是已核验外卷即失败。输出在另一外卷时分别校验，不能假设两个 UUID 相同。源路径不执行 probe/mkdir/lock/write。
4. 检查已安装 DuckDB 与受限配置可用；不得以缺依赖为由访问数据库或自动安装。源/输出门禁通过后取得 `.state/archive.lock` 的 OS flock，再打开派生的本机 SQLite；失败不发 HTTP。
5. 初始化或迁移账本，再枚举。每个日文件打开、批次读取前后、指纹完成及日封存前核验来源卷；输出卷继续在批次、HTTP 与文件提升边界核验。流块使用已有低成本挂载/设备/fd 检查，不逐块运行 diskutil。
6. 任一必需卷失效时 blocked/cancelled，保留已提交 PDF 和本机诊断；不能按同名挂载目录重开、回落系统盘或通过临时拷贝 Raw 绕过问题。

SQLite 沿用 DELETE journal、synchronous=FULL 和本机路径；目录句柄不被误称为 sqlite3 dir_fd 支持。迁移、枚举与文件提交都在同归档根独占锁下进行；不取得 DG 写锁，不修改调度或同步进程。

## 4. DG Raw 只读枚举与封存

### 4.1 输入合同与扫描

start/end 保持原 ISO 语法和闭区间；按自然日递增生成路径，每次只打开一天。数据集当前从 2020-01-01 开始；不缩窄现有 CLI 日期语法，所请求日文件缺失就明确报缺日，不能猜为空或截断范围。固定唯一 part-000.parquet，不 glob staging/candidate/其他 part，不依据 DG 事件数量推断文件存在。

物理 schema 必须是固定顺序六列 VARCHAR：`ann_date, ts_code, name, title, url, rec_time`，读取禁用 hive_partitioning。投影全部六列，不加 id/hash/group 字段，不 SELECT *。所有非 NULL 值必须是字符串；Raw YYYYMMDD 严格解析并等于当前 ISO 分区日期，不能以目录字段补齐错误 Raw 日期。其他字段的 NULL、空串和空白原样保留；不调用股票基本信息库/交易日/对象池过滤。

目标单日 SQL（路径参数是已固定句柄；不按绝对路径再次打开）：

```sql
SELECT ann_date, ts_code, name, title, url, rec_time
FROM read_parquet(?, hive_partitioning=false);
```

参数为 `/dev/fd/<fd>`。DuckDB 1.5.5/macOS 机制已用临时文件验证；其他平台或不支持 fd 路径的环境明确失败，不能改为逐批重开路径。source 使用同一个查询结果 `fetchmany(500)` 迭代，不能 OFFSET 或每批执行同一全日 SQL；无需全日 ORDER BY/DISTINCT，也不把查询结果转成整日 list/DataFrame。固定 fd 保持到全部批次和日指纹核验结束。

### 4.2 并发一致性和日校验

来源按日 os.replace；读者持有旧 inode，路径新版不影响这一日。不要比较“当前路径仍是旧 inode”作为完成条件，否则正常每日更新会错误阻断。记录打开版本的 fstat 身份、size、SHA-256 与 footer 行数；在打开 fd 上用 64 KiB pread 块生成读取前/后指纹，不改变查询使用的文件位置；核验两次指纹及 dev/ino/size/mtime 一致。原子替换可能改变旧 inode 的 ctime/nlink，不能把这两项变化当作内容变化。路径指向新版可以完成旧版读取，同一 inode 原地改变则 source_file_changed 阻断。

schema/footer 从同一固定 fd 读取。读取行数必须等于该版本 footer 行数；每行日期/类型均验证。源六字段重复通过账本同一 run 的 record_key 再次出现检测，不能消费时去重后宣称 Raw 符合合同；发现重复记 source_duplicate_record 并阻断。NULL URL/rec_time 不算合同错误。合法完整 schema 的零行文件封存为 0 行；缺失/损坏/schema 或分区错误均阻断。

运行最多一个固定日文件句柄、一条活动 DuckDB 查询、一批 500 行。每日本身创建并关闭独立 DuckDB 连接，不能跨日复用连接缓存 `/dev/fd/同编号`；DuckDB 内部临时打开的句柄也须随连接关闭，不宣称全进程只有一个 fd。日级最多两次指纹流读及一次数据扫描，另有有界 schema/footer 读取；扫描量与输入文件字节相关。指纹/批次循环检查取消，查询/元数据调用采用 15s watchdog 调用 connection.interrupt()；计时器每次调用结束撤销，连接只能在调用结束后关闭。独立进程测试必须证明超时和 Ctrl+C 会停止领取、线程结束且不遗留查询；若实测 interrupt 无法在预算内退出，停止实现验收并修订本节，不能无界等待或引入隐式全文件缓存。

### 4.3 持久化边界与下载输入

begin_run 后各日记 reading，每批 source_records、run_artifacts、records_read/missing_url_count/artifacts_total 和该日 records_committed 在同一 SQLite 短事务保存。失败不推进计数；已提交批次保留。日校验通过在一个事务写 size/hash/footer_count、completed 状态及完成日计数；阻断/取消时保存当前日 blocked/cancelled 与原因，不虚增完成日数。枚举期间禁止 HTTP，包括先读完第一日就边枚举边下载。

所有日期 completed 且 committed_count=footer_count 才能将 runs.enumeration_sealed=1、phase=downloading 一次提交；next_task 必须拒绝未封存 run。下载只领取这一 run_artifacts 的冻结集合，不向实时 Raw 做 has_artifact 查询，不按每文件重扫 Parquet。源后来新增记录在下一次命令纳入。

日快照不是跨日期整体快照；封存只证明读过这些版本并满足 consumer 合同，不产生或替代 DG materialization/check/readiness 状态。DG 对源的完整分页及日常稳定性由原 DG 接入方案验收。

退出或失败的新命令从所选日期首日重新枚举，保留旧日事实用于诊断；不使用旧行号跳进可能更新的文件。文件级续跑依靠稳定 artifact_key，而不是旧 upper_id/after_id。无 URL 行只有来源映射，没有任务。枚举缺日时整轮 blocked/零 HTTP，不清理先前已成功 PDF。

## 5. 身份、SQLite schema 2 与迁移

### 5.1 两种身份

原 `core.identity` 的 JSON 数组、ensure_ascii=False、固定 separators、UTF-8 SHA-256 算法保持。目标身份明确为：

```text
record_key = identity(["dg-anns-d-v1", raw_ann_date, raw_ts_code,
                       raw_name, raw_title, raw_url, raw_rec_time])
artifact_key = identity([ISO(raw_ann_date), raw_ts_code, raw_url.strip()])
```

record_key 的原值不 trim/补空/转时区/NFC；JSON null 和 "" 不同。它是下载台账的来源映射指纹，不写回 Raw，不代表 Prod hash。URL NULL/去空白后为空时 artifact_key=NULL，记录 skipped_missing_url；其他非法字段仍保留来源映射，文件验证沿用 invalid_title/invalid_ts_code/invalid_url。

source_scope 从 DG 来源卷 UUID、卷内 raw/tushare/anns_d 路径、合同版本生成，带明确 dg-anns-d 标识。旧 Prod scope/hash 按原值保留，不能冒充 DG six-field key。归档身份仍由输出卷 UUID 与相对目录生成，不能把来源切换加入归档身份导致旧台账找不到。

Raw 20260726 的下载投影须为 2026-07-26；同代码/trim 后 URL 得到旧 key。name/title/rec_time 不同的源记录分别映射到同一 artifacts；原路径/首次标题不改。跨日期/代码仍分别下载，不新增跨目录链接或全盘去重。六字段完整原 JSON 存在 source_records.metadata；用于下载的规范日期/URL 与原值分开，不能覆盖 metadata。

### 5.2 表与事务

| 表 | schema 2 目标 |
| --- | --- |
| archive | 原 volume_uuid/root_relative_path/created_at，schema_version=2；不得生成新归档身份 |
| runs | 原范围/间隔/计数/阶段保留；新增 source_kind、source_contract_version、source_policy、days_total/days_completed/current_day、enumeration_sealed 默认 0；旧 upper_id/after_id 重命名 legacy_upper_id/legacy_after_id，仅历史诊断 |
| source_records | 原 PK(source_scope,row_key_hash) 随列重命名为 PK(source_scope,record_key)；raw_id→legacy_raw_id；metadata/artifact_key/first_seen_run/last_seen_run 保留，DG 行 legacy_raw_id=NULL |
| run_source_days（新增） | PK(run_id,ann_date)；state、opened_dev/ino、size、sha256、footer_count、records_committed、reason、updated_at；只保存读取事实，不复制文件或做 DG readiness 摘要 |
| artifacts | 原主键/路径/path_fold/title/URL/state/attempts/size/sha256 原样保留，供两种历史来源复用 |
| run_artifacts | 原 PK(run_id,artifact_key)、outcome/attempts 与 pending 索引保留；只能消费已封存新 run |
| cooldown | 原单行时间/in_flight/reason 保留，不因迁移缩短等待 |

新鲜初始化直接建 schema 2。已有 schema 1 在取得归档 OS 锁并核对 archive 卷身份后升级：先验证已知表/列/主键/唯一索引；BEGIN IMMEDIATE；早期 schema 1 若缺 missing_url_count，在该事务中补默认 0（旧程序同样支持该已知形态），不猜测其他缺列；显式逐条 ALTER TABLE/CREATE TABLE/索引调整；旧 runs 标注 source_kind=prod_postgres（历史），新字段不虚构其读取日数/指纹；最后更新 archive.schema_version 并 COMMIT。不能先执行新 schema 的建表脚本再核验版本，不能用会隐式提交的 executescript 包裹迁移。未知/更高版本或非本归档账本直接阻断。

列重命名只改变标签，不重算旧 hash/id 或改旧 metadata；legacy 字段仅存历史数据，不保留 PG 运行分支。新代码只创建 DG run，DG 插入显式列清单，禁止 INSERT VALUES 依赖旧列顺序。全部 SQL/fixtures/查询消费者一次迁移到新列名。失败 ROLLBACK，旧版本/行数/索引/冷却与文件原样可读；不清空、重建、备份或删除账本/PDF。升级后旧程序遇 schema_version 不匹配应停止；不提供降级写入。

每批事务内为新来源指纹保存 metadata/首次及末次 run；同 run 已存在该 key 即重复源合同错误，回滚本批。新 run 再见同 key 更新 last_seen_run 不算重复。run_artifacts INSERT OR IGNORE 的新增量与 artifacts_total 同事务维护；completed/outcome 变更同事务更新增量计数。stats 仅读 runs 单行，不能全表 COUNT/GROUP BY 做心跳。日表索引支持按 run/state 查询，next_task 仍走原 pending 索引。

文件 states 继续 pending→downloading→prepared→succeeded，失败/阻断分开；run 继续 enumerating/downloading/completed/partial_failed/cancelled/blocked。进程异常退出后启动将旧活动 run 记 cancelled/process_exit_recovered，不删除其已入账行。新 run 再枚举、封存及文件恢复；历史 attempts 与本轮 attempts 分开，每轮最多 3 次。

## 6. 命名、校验、提交与删除后重下

沿用 Files.allocate/receive/promote/recover。完整 ts_code 通过路径安全校验；title 清洗 NFC、不安全字符及 UTF-8 截断，以 title.pdf 优先，碰撞追加 artifact_key 短 hash 逐级延长；path_fold 唯一处理大小写等价，保留未知文件、不覆写。不因来源切换重新分配已有成功路径。

仅 http(s) URL，TLS 验证开启。标题为空/非法代码/URL 标记当前文件失败，元数据仍在台账。正文写同目录 `.<artifact_key>.part`，64 KiB 块、size/SHA-256、PDF header/EOF、Content-Length/编码/非 HTML/512 MiB 上限校验；fsync 后先记 prepared，再 os.replace 并同步目录，最后记 succeeded。SQLite 写成功前不报告成功；写失败停止后续领取，不回滚已提交 PDF。

| 账本/物理状态 | 新轮次恢复动作 |
| --- | --- |
| succeeded，size/hash 一致 | 有效跳过，零 HTTP |
| succeeded，用户已删除 final | pending，按原身份及安全路径重新下载；台账不能永久阻止 |
| succeeded，损坏或未知文件占用 | 保存原文件，分配安全新路径重下 |
| downloading，只有不完整 part | 文件从头重下；其他已完成文件保留 |
| prepared，part 匹配且 final 不存在 | 原子提升并补成功，零 HTTP |
| prepared，final 匹配 | 补成功，零 HTTP |
| prepared 均不匹配、符号链接或多硬链接 | 沿用恢复失败/安全阻断，不猜成功、不覆盖 |

同 URL 远端内容修改不在本次探测范围；不做 Range 字节续传、自动重命名旧成果、未知文件删除或额外文件备份。

## 7. 请求间隔、取消与故障

沿用全局 Limiter，所有实际 GET/重试/每跳 redirect 在请求前核验输出卷并遵守 `max(间隔,持久冷却,服务器要求)`；httpx 禁自动重定向/重试，禁止 HTTPS 降级与循环，最多 5 跳。请求开始落 in_flight、结束落冷却，失败不能继续请求；重启不能缩短已有 next_request_not_before，未知结束至少等待本轮 interval。

超时/连接错误/408/429/5xx 最多 3 次，退避 30/60/120s，Retry-After 支持秒与 HTTP 日期；403/验证码使 run blocked，停止后续；404/410/非法 PDF 等文件 failed，其他文件仍限速执行。缺源文件/schema/读取超时/源卷丢失/SQLite/锁错误使 run blocked，不回落 Prod 或启动 DG。

取消检查覆盖源 fd 指纹块、日和批次前后、SQLite 提交前后、每个 HTTP 开始/结束、传输块、≤0.5s 等待、prepared/rename 边界；Control 心跳 ≤5s。DuckDB watchdog 与 Control 协作，取消触发 interrupt，必须安全等待查询结束再释放 fd/connection，不在活动查询期间关闭句柄。网络正在阻塞的 read 仍受 15s 超时约束；不承诺任意系统 I/O 瞬间终止。退出保留所有已提交 unit。

## 8. 进度、退出码与性能验收

枚举显示 current_day、days_completed/days_total、records_read、artifacts_total、missing_url_count、更新时间；活动日同时显示 records_committed/footer_count，按已提交业务计数更新。源指纹/查询中只显示当前子阶段和上次确认量，不能把心跳当行增长。范围整体记录总量未确定时不伪造记录百分比；枚举封存后以 run_artifacts 为下载分母，并用 ann_date 显示当前文件日期（current_day 保留读源窗口上下文）。

退出码沿用：0=文件全部成功或有效跳过，含合法零任务范围；1=存在文件失败；2=参数/启动依赖/磁盘门禁失败；3=运行阻断；130=用户取消。运行期缺日不是 0 行成功。可记录 reason code、脱敏来源及当前日，不输出连接串/错误页/敏感 URL query。

输入已知上界证据为历史最大日 69,498 行，当前证据总行数 12,064,773（均为历史时点）。成本为 O(日期文件总字节+源行数+新增任务)，SQLite B=Σceil(日行数/500) 次枚举提交；源内存预算 256 MiB/1 线程/no-spill，Python 500 行及 64 KiB 块。它不等于全进程 RSS 上限；单批字符串大小和台账增长须实测。不存在全历史 DB 事务、Tushare 配额或逐 PDF 元数据 SQL。

实现后先在空日、小日、最大日量级只读 profiling，记录 fd 数/查询次数/扫描字节、读取和落账时间、峰值 RSS、每行台账空间、取消延迟；最大日量级每个读取调用应在 15s 内完成，进度间隔≤5s。不能满足预算则阻断并回写方案，不静默增加限制。只有按已测样本算清选定日期枚举耗时、台账/磁盘空间、文件请求量及预计范围耗时才进入范围执行；PDF 网络计时样本只在最小真实阶段获取，不为 profiling 提前下载大量文件。

## 9. 开发硬口径与验收映射（隔离/只读证据见 §14，真实下载另验）

| 约束 | 目标代码点 | 正向证据 | 负向/故障证据 |
| --- | --- | --- | --- |
| R1 单一 DG 来源 | CLI.main、source 工厂 | 无 PG/CH/DG 进程也读 fixture；现有四参数 | monkeypatch DB/Tushare 建连即报错，证明未调用；缺 DuckDB/源无 fallback |
| R2 全自然日范围 | Source.iter_days/DayReader.__iter__ | 两端/周末/空日、退市与债券代码都纳入 | 前后一天不得混入；缺一日整轮 blocked/零 HTTP；非法 Raw 日期不补值 |
| R3 日期与旧 key | core.identity、源下载投影 | 固定旧金样本 2026-07-26 与 Raw 20260726 得同 key | 直接八位 date 会得不同 key 的反例；跨日/代码不同 key |
| R4 六字段与标题 | source、Ledger.ingest、Files.allocate | 六字段原值、同 URL 多映射单任务、旧路径不改 | NULL/空串/空白/name/rec_time 差异不得合并；非法标题/代码保留来源并失败 |
| R5 限速 | Limiter/Downloader/cooldown | fake clock 和本地 HTTP 时间戳 | redirect/retry 绕过、NaN/inf/负数、迁移/重启缩短冷却 |
| R6 恢复与复用 | Files.recover/ledger v2 | schema 1 五个成功旧 key 升级后零 GET；删除一份后仅请求这一份 | prepared 两窗口、损坏保留重下、退出/rename 后记账失败；错卷不复用 |
| R7 双卷门禁 | Volume/source 只读锚点 | 同卷/不同外卷，外盘确认先于读取/账本/HTTP | 内盘、未挂载、只读输出、路径符号链接、源/输出换 UUID、失败不得建挂载目录 |
| R8 新运行重枚举 | Source/Ledger.begin_run | 下次加入新版记录，已有文件有效跳过 | 从旧 id/行号跳读不得出现；旧范围任务不能领取 |
| R9 固定日版本/封存 | fd reader/run_source_days/next_task | 读取到半批后 os.replace，全部行来自旧版；ctime/nlink 改变仍允许；下轮全新版 | 原地改写/坏 footer/读数不符/重复源/任一缺日阻断；未封存调用 next_task 禁止 |
| R10 有界读取 | query/fetchmany/Policy | 501+跨批、69,498 行量级；一次固定一日/一查询、单批≤500；跨日复用 fd 编号不会混入缓存旧数据 | 禁 fetchall/OFFSET/全范围 list/逐文件 read_parquet；no-spill/扩展网络反例 |
| R11 原子迁移/持久化 | Ledger 升级/批次/封存 | v1 金样本升级保留全部状态；v2 重开无重复迁移 | 中途 DDL 故障回滚、未知版本/旧程序拒绝、批次失败不推进、SIGKILL 后新轮恢复 |
| 取消/进度/终态 | Control/runner/Source | 查询 interrupt、独立子进程中断—重启、计数单调 | 查询超时不遗留线程/fd，冷却取消，台账写失败停止而保留 PDF；心跳无业务量不算进度 |

隔离 fixture 用现有 DuckDB 生成临时 Parquet，expected 六字段/旧 key 必须是独立字面金样本，不能通过被测 helper 反向生成；旧账本 fixture 采用实际 schema 1，所有 files/HTTP 不变规则继续回归。测试不访问正式 Lake、Prod 或真实 PDF，不安装依赖。

之后只读验收已通过历史文件：至少空日、2026-07-26 五条日、缺 URL/rec_time 的已知样本及最大日量级；对照实际六字段、行数、批次数和记录→文件映射，记录数量/样本与 profiling。需要大日 fixtures 时不把合成量级当实际数据证据，不把仅文件存在标为 DG ready。

最小真实阶段另按授权选择最多 5 个唯一 URL：先验证既有 Prod 成功文件在同归档根复用零请求，删除文件只在用户明确同意的验收文件范围做；随后下载—取消—续跑—零请求重放—size/hash 读回。记录来源 run/day/hash、源行数、唯一任务数、每次请求及间隔、物理成果。不自动卸载承载其他任务的磁盘；真实拔盘仍须另有现场验收。

## 10. 本轮分析、验证与下一步

2026-10-05 使用 CodeGraph `codegraph_explore` 覆盖 CLI、source、Ledger、Files/Volume 调用关系，补读真实 main/execute、Policy、账本 SQL、文件恢复、专项 tests、DG contract/path/promote_day 与现有 Foundation Lake reader。影响面集中于工具入口→来源枚举→SQLite→文件恢复；没有把静态调用结果当作全量动态消费者证据，旧 SQL fixtures/直接账本字段消费者以 rg 搜索核验。未发现本次需要修改的前端/API 消费者；数据中心尚属后续设计。

临时文件机制验证：根现有 .venv 的 DuckDB 1.5.5，旧文件 fd 打开后 os.replace 路径；read_parquet('/dev/fd/<fd>', hive_partitioning=false) 读 old，重开路径读 new。复测确认旧 fd 的 dev/ino/size/mtime 不变，nlink 从 1 变 0、ctime 改变；256 MiB/1 线程/no-spill/禁止自动扩展的连接配置可建立。临时目录清理，不读取/写入正式 Lake，不下载 PDF。此证据只支持 §4 固定 fd 与属性核验选择，不是新增自动化测试、性能预算或真实下载已通过的声明。

按技术方案 §9，迁移实现和隔离/只读阶段先完成，随后经用户授权完成 §15 五 URL 真实验收；CLI 四参数不变，来源明确切 DG，移除数据库读取。schema 升级已有独立旧验收台账的真实证据，默认归档台账未升级。依赖矩阵、DatasetDefinition、DG 数据集/API/前端均未改变。台账查询/维护的后续实现与验收见 §16；数据中心页面/API/Figma 工作开始前停下，待产品细节和 Figma 讨论完成后另行授权。DG 连续日常验证独立进行。

方案提交前文档完整性三组、两份文档 21 个引用及差异检查通过；实施阶段又核验新增引用，结果见 §14。R1—R11 在两份原设计中均有对应约束/验收映射。文档检查不证明新代码行为。以下保留 Prod 版本历史证据，段落中的阶段指引只表示记录当时状态。旧分组覆盖/id 删除已经失效，旧逐文件 DB 存在性复核仅描述已被替代的 Prod 实现，不适用于上述目标 DG reader。

## 11. M0/M1 实施证据（2026-10-01）

- M0：文档完整性、链接与空白检查通过，设计文件及索引提交 `45c19af3`；用户随后明确授权 M0/M1。
- 环境：仓库 `.venv/bin/python` 可导入 httpx、SQLAlchemy、psycopg、pytest，未安装或升级依赖。
- M1：新增 §1 列出的工具与测试，`--help` 可用，参数错误在任何磁盘/数据库动作前退出；外盘失败在配置、账本及数据库连接前退出。
- 基础专项用例：52 项通过。覆盖日期边界、显式数据库配置及原优先级、URL 去重、新公告重扫、未知文件防覆盖、损坏文件保留重下、准备态恢复、rename 后成功记账失败、取消后续跑、枚举批次回滚/崩溃、重定向/重试/持久冷却、请求 0 间隔、403 与验证码停止、非法 PDF、外盘身份变更、无挂载不建目录、符号链接、互斥锁、空间及 fsync 错误、进度单调和结果幂等。
- 架构护栏：主体依赖矩阵、Platform 与 Operations legacy 护栏共 16 项通过；不扩展为对全仓功能的回归证明。
- Prod 只读性能：经既有 psql-remote 入口、READ ONLY、15 秒 statement_timeout 执行两条 EXPLAIN ANALYZE，仅返回计划。2026-09-30 首批返回上限 500 行，执行 310.883ms，Top-N sort 318kB；2025-01-01～2026-09-30 首批上限 500 行，执行 3.616ms。窄范围诊断计划读取大量主键索引条目，不能把 LIMIT 当作访问量上限；本轮未增加生产索引或修改数据库配置。
- 只读磁盘证据：系统 diskutil 确认 datasource 挂载 APFS 外盘及其物理 store；未执行真实目录创建、可写探针、PDF 下载或拔盘测试。隔离测试使用临时目录和合成卷属性，不替代 M3。
- M1 与 LLD 的实施校准：增加 core.py 集中策略；暂存 basename 固定为 artifact_key；进度计数改为单行读取；正文期限明确受单次 read timeout 的退出边界约束，未增加新的 CLI 参数或业务能力。

下一阶段为 M2 专项验收，需单独按阶段确认；真实 URL 下载与正式外盘写入仍由 M3 承担。本轮不创建调度、不发起公告元数据维护或全量下载。


### 2026-10-02 旧分组方案与 Prod 消费者记录（已被替代）

元数据同步仍由既有anns_d主链负责。2026-10-02用户确定Raw物理只留不被覆盖版本，下载枚举继续显式读取Raw id和row_key_hash，无需is_current过滤。上界id只是本轮枚举边界，不是永久公告身份；每次新轮次从0重枚举。被完整记录替代的旧id可以被删除，新版获得新id；元数据内容指纹可能变化，文件身份仍是日期、代码、URL。

URL NULL/空值：保存该行的本地来源映射，记录skipped_missing_url，并推进同批游标；不创建空URL下载身份、不发HTTP、不让NULL.strip()中断批次。非空但非法URL按既有invalid_url文件失败口径，不丢公告元数据。rec_time为NULL只影响元数据展示，不影响文件任务。

本地source_records.artifact_key在无URL情况下需要允许NULL/无关联；后续新有效URL版本可创建文件任务。新一轮不纳入已经物理删除的冗余记录及其新下载任务，不删除旧轮次已经验证成功的文件。每次领取文件前按日期、代码、URL复核至少一个对应公告仍存在，不能只凭旧id存在与否判断同一URL文件是否需要，避免枚举后被覆盖继续下载；查询需短只读有界，不自动删除账本映射。跨轮次成功文件按既有日期/代码/URL身份复用。

适配验证：物理替代后的旧来源映射不错误领取、缺URL映射/统计/游标同事务、缺时间可下载、代表换ID相同URL不重复下载、旧轮次未完成文件的有效性复核、非完整性快照边界。现行M1没有上述NULL与覆盖适配，不能在新公告合同部署后直接当作已兼容运行。


### 2026-10-02 Prod 消费者适配记录

无 URL 的公告写入本地 source_records，artifact_key 为 NULL，不领取 HTTP 请求；游标与 missing_url_count 同一 SQLite 事务提交，输出 skipped_missing_url。已有账本通过显式 ADD COLUMN 补 run 计数，不清空记录。

文件身份仍为日期/代码/URL；领取前以短只读事务查询该文件身份是否仍存在，不能用可能被删除的 raw id 当永久身份。若已无该文件身份，标记 skipped、reason=source_record_replaced；新版保留同 URL 时仍可复用已完成文件。新轮次重新枚举，当前轮次冻结的 upper_id 不保证发现随后新增版本；已有 PDF 不删除。每文件复查查询使用 ts_code/ann_date 现有索引，Prod 代表性性能待 M3 验证。

P1 回归包含缺 URL 不请求、游标提交/回滚、被替代来源不请求；已有成功文件恢复和身份测试继续通过。未进行真实 HTTP 下载或写入正式外盘。


## 12. M2 专项隔离验收（2026-10-03）

依据为§2—§9既有硬口径，不新增CLI参数、配置、请求头或业务能力。管理员授权继续推进后，先提交生产同步只读证据ffca591f，再完成本阶段。测试使用临时目录、模拟卷、本地127.0.0.1临时HTTP服务以及独立Python子进程；没有请求真实公告网站、连接业务数据库或写正式外盘，也没有安装依赖。

新增反例先复现三个实际缺口：ts_code/title为NULL时原代码抛出未处理TypeError；恢复已完成文件时未拒绝多硬链接。修复集中在files.py：非法代码/标题按既有invalid_ts_code/invalid_title记录文件失败，尚未发请求；指纹恢复发现多硬链接以multiple_hardlinks_forbidden阻断，保留原文件和外部链接。这符合§6原规则，没有修改Raw保存口径。当前Prod对应缺失字段为0，反例覆盖未来合法保留的异常源记录。

| 硬口径 | 真实代码与本阶段证据 |
|---|---|
| 日期/间隔参数、显式数据库、先外盘后连接 | CLI/options/source；既有非法日期/间隔、配置优先级、只读事务及启动顺序测试 |
| 指定日期范围、每批500和短只读事务 | Source.batch/transaction；闭区间、SQL绑定参数与statement_timeout测试，原范围未完成任务不会被新范围领取 |
| 日期/代码/标题目录与无覆盖 | Files.allocate/title_name、Ledger.assign_path；中文、UTF-8预算、NULL与非法路径反例，NFC及casefold四文件不冲突、未知文件保留 |
| 外部真实介质与路径边界 | Volume.open/assert_valid；内部盘/只读/未挂载/换UUID/拔盘/符号链接/空间与fsync故障；三种禁止Lake根均在建目录前拒绝 |
| 串行请求、重定向/重试同样限速 | Downloader/Limiter；真实本地HTTP一次重定向、一次503、重试后再次重定向共4请求，设置0.05秒后每次服务端开始与前次结束相隔至少0.045秒；精确5秒、90秒和debug0由fake clock测试证明 |
| 服务器冷却与取消 | Limiter/cooldown/Control；Retry-After秒与日期、重启不可缩短冷却、等待中取消、403/验证码停止领取 |
| 格式与传输校验 | Files.receive；真实HTTP长度截断触发3次尝试且无最终PDF；HTML/压缩编码/超限/缺EOF反例；分块超时和EOF时超时均不能提升 |
| 单批与分块边界 | Source.batch、Files.receive；SQL批次500、8个64KiB块接收期间均保持downloading，EOF后才prepared/promote；这是行为边界证据，不是全量RSS或容量测量 |
| 进程退出和幂等恢复 | 三个独立子进程os._exit(73)：下载第二文件时退出保留第一个成功文件，重启只请求一个未完成文件；prepared未提升及rename后未记成功分别退出，重启均零HTTP且正确恢复；旧run记cancelled/process_exit_recovered，完成文件读回一致 |
| 文件归属安全 | Files.fingerprint/receive；已完成文件多硬链接阻断并保留内容，既有符号链接与非安全暂存反例 |
| 观测与落账隔离 | Ledger/execute；结果幂等与百分比单调、枚举失败保留批次、rename后SQLite失败保留prepared证据；缺URL映射/游标/统计同事务，不发请求 |

验证：下载专项72项、架构护栏16项，共88项通过；--help、compileall、文档完整性及git diff --check通过。CodeGraph files/query/impact覆盖Downloader、Files及CLI execute，并补读source、ledger、volume、HTTP、文件提交和专项测试；不新增业务分层、依赖方向、API/CLI入口或注册。CodeGraph的静态调用分析不替代真实子进程和HTTP结果。

M2完成不等于M3完成。下一阶段按§9最多5个真实URL，在正式外盘执行下载—中断—续跑—读回，先核验现有挂载、数据库连接和查询性能；不自动启动全历史PDF下载。真实容量、源站限制以及实际外卷断开/重挂载语义仍需现场证据。


## 13. M3 最小真实验收（2026-10-03）

管理员明确授权M3后，使用真实CLI main、现有.env.web.local连接与Source只读事务，选取2026-07-26的完整自然日。Prod该日恰好5条公告/5个URL，均来自static.cninfo.com.cn；未增加抽样或对象过滤参数。临时观察脚本仅附加httpx请求/响应及Limiter.after事件记录，不替换真实网络、数据库、文件提交或卷检查，也不提交为新的产品入口。机器可读证据见[验收报告](/Users/congming/github/goldenshare/reports/anns_d_pdf_m3_acceptance_20261003.json)。

外盘实测为datasource/APFS、Internal=false、可写、UUID 8C5A534D-EAE1-42A2-A7D5-D24DEB820E29，physical store disk6s2，具备外置设备DeviceTreePath。真实Volume.open探针、固定目录fd、OS互斥、空间检查、文件/目录fsync及原子提升均完成；未卸载或拔除承载其他任务的外盘，实际断开/重挂载仍未验证，相关失败路径由M2故障注入覆盖。

首轮使用默认/Volumes/datasource/announcements，5份文件、5次GET均200，最短请求结束至下一开始5.154秒、无重定向/重试/验证码；每份Content-Length与接收字节一致。首轮取消验收未通过：stdout连接管道时print缓冲，观察程序直到下载全部完成才收到首份成功事件，SIGINT在结束阶段导致退出-2，账本及5份成功文件已完整提交。未将此轮当作有效取消，原文件及证据保留。

修复core.Control默认输出立即flush，不改变进度字段/CLI参数，也不要求调用方设置Python无缓冲环境。新增独立进程管道测试先复现运行中无输出，再验证退出前可读；73项专项+16项架构护栏共89项通过。CodeGraph query定位Control，impact因同名符号歧义补用源码核验CLI、HTTP/files及测试消费者；没有新增依赖或业务配置。

为保留已完成成果并实际检验未完成任务恢复，同5个URL在/Volumes/datasource/announcements/m3-interrupt-acceptance-20261003复测，使用独立归档身份/账本。组织层次仍为日期/完整代码/标题.pdf。

| 运行 | 退出码/终态 | 源记录/文件任务 | 本轮成功 | 有效跳过 | HTTP请求 |
|---|---|---|---:|---:|---:|
| 首份成功后SIGINT | 130/cancelled | 5/5 | 1 | 0 | 1 |
| 同命令续跑 | 0/completed | 5/5 | 4 | 1 | 4 |
| 再次同命令 | 0/completed | 5/5 | 0 | 5 | 0 |

复测5次响应全部200/application/pdf，无重定向或重试，4个请求结束至下一开始间隔最小5.148秒，包含取消后重启的间隔。5份物理文件大小及SHA256全部与本地SQLite账本一致，总计925,599字节，单份109,946—346,832字节；中断后成功文件未重新请求。默认目录和独立复测目录各保留5份，总计10份物理验收文件、仍只有5个不同源URL，没有删除已成功文件或清空账本。

Prod查询性能经READ ONLY及15秒超时验证：窄范围首批5行0.569ms，after_id=20080449后续2行0.109ms；2020-01-01至2026-09-30、after_id=15000000宽范围后续批500行3.059ms；代码/日期/URL复核LIMIT1为0.639ms。日期查询使用既有日期索引，宽范围使用主键索引，未改数据库、索引、超时预算或业务表；这些代表性查询不能保证任意未来数据分布均相同。

CLI复测命令（已有环境文件，不输出连接密码）：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -m src.scripts.download_announcements \
  --start-date 2026-07-26 --end-date 2026-07-26 --interval-seconds 5 \
  --output-root /Volumes/datasource/announcements/m3-interrupt-acceptance-20261003
```

范围边界：本轮没有写Prod、启动元数据同步、下载全历史或安装依赖。只验证巨潮静态域名及5个小文件；其他域名、真实拔盘、全范围容量和实际运行预算没有本轮证据。M4须由管理员指定日期和请求间隔，不能把5个样本均值外推为1200万份的磁盘或耗时预算。


## 14. DG 迁移实现与隔离/只读验收（2026-10-05）

方案提交 777d6901 后，用户授权继续推进。源与台账升级按 §1—§9 实施；正式 Lake 只读，本轮未运行真实 PDF 下载、升级正式账本、删除用户 PDF、触发 DG job/事件/调度或安装依赖。[完整验收](../../reports/anns_d_download_dg_reader_acceptance_20261005.md)、[机器可读证据](../../reports/anns_d_download_dg_reader_acceptance_20261005.json)。

R1—R11 的代码点为 CLI.main/execute、Source/DayReader、SourceVolume、source_projection、Ledger._upgrade/begin_day/ingest/complete_day/seal/next_task，以及未改的 Files/Downloader。tests/test_announcement_download_cli.py 全部迁移到日迭代/封存；tests/test_announcement_download_dg.py 验证真实临时 Parquet 与历史 schema 1 金样本。SQL 和测试消费者已清零运行期 configured_database/id 游标/has_artifact，旧字段只留在事务迁移及历史诊断，不保留 PG 执行分支。

冻结旧版构造器与 SQL 仅作为迁移测试金样本，不被产品导入。五份隔离旧 PDF 升级后零请求，删除其中一份只请求这一份；prepared 两窗口、未知版本、缺唯一约束、DDL 中途回滚、旧程序拒绝新账本和早期可选计数列均验证。独立进程枚举中退出保留第一批，重启重新枚举；实际 SIGINT 中断长 DuckDB 查询得到 run/day cancelled、零请求；超时/取消 watcher 回收。原本机 HTTP redirect/retry/冷却测试继续通过。

正式只读选择合法空日 2026-09-26、五条日 2026-07-26、缺字段样本 2023-06-09 和冻结计划最大存量日 2024-04-26；合计 76,685 条、156 批、42,032 唯一文件任务，缺 URL 1 条、rec_time NULL 29,443 条均保留映射。六字段/逐行日期/类型、无完整重复、fd 前后指纹、footer 与 SQLite 行数、日完成及范围封存均对账一致；没有请求 PDF。它不证明全历史/Tushare 完整性或 DG 日常稳定性。

最大日 69,138 条，139 批，读源和临时落账 39.077 秒，其中 SQL 6.053 秒，单次 DuckDB 调用最大 0.006 秒，进度最大间隔 0.33 秒；整体 RSS 峰值 128.78 MiB。正式归档的双卷核验/文件恢复/网络开销不在本次只读秒数中。台账 88,813,568 字节，样本平均 1158.16 字节/行；全文记录/索引会占空间，不能把 DuckDB 内存限制当台账容量保证或直接据样本承诺全量耗时。

CodeGraph explore/search + sync/status（up to date）复核 CLI→Source/SourceVolume→Ledger→Files/HTTP，补用实际 SQL、源码和 tests 搜索核验所有消费者。未修改子系统边界、API、DatasetDefinition、DG 接入合同或数据维护执行计划。下一步另按阶段执行 DG 最小真实下载，台账查询维护和前端继续后续工作。

验收数量：下载专项与架构共 129 项通过，--help、compileall、文档完整性、26 个引用和 git diff --check 通过；没有安装依赖或合入其他工作区改动。

## 15. DG 五 URL 最小真实归档验收（2026-10-05）

用户要求提交代码并继续推进，先提交下载器实现、测试和 §14 证据为 9f8faacf，再执行本节验收。[真实报告](../../reports/anns_d_download_dg_pdf_acceptance_20261005.md)、[运行/网络/文件证据](../../reports/anns_d_download_dg_pdf_acceptance_20261005.json)。本节是 §14 之后的新阶段，前述只读阶段记录保留。

选 DG Raw 2026-07-26 完整自然日，五条六字段记录、五个不同 URL，来源指纹与 §14 一致。默认归档已有其他九月批次，本轮只读检查后保持原 schema 1 和记录；升级验收使用既有独立目录 `/Volumes/datasource/announcements/m3-interrupt-acceptance-20261003`。真实 schema 1→2 后，五条 artifacts 全部字段、五条旧来源映射和三次旧运行原有字段保留；另建 DG 映射并复用同一 artifact_key。五份已有 PDF 全部跳过，零 GET。

新目录 `/Volumes/datasource/announcements/dg-source-acceptance-20261005` 在执行前不存在，派生台账也不存在。真实 CLI main 完成输出/源双卷核验、逐日落账与指纹/footer对账、范围封存、HTTP、fsync 与原子提交。临时观察不替换真实网络/源/文件链，只限制已核验五 URL 和每轮请求预算、记录请求/响应及 Limiter.after；父进程读到首份成功后发送实际 OS SIGINT。

| 运行 | 退出码 / 终态 | 成功 / 跳过 / 失败 | GET |
| --- | --- | --- | ---: |
| 旧归档复用 | 0 / completed | 0 / 5 / 0 | 0 |
| 新目录首份后 SIGINT | 130 / cancelled | 1 / 0 / 0 | 1 |
| 同命令续跑 | 0 / completed | 4 / 1 / 0 | 4 |
| 再次同命令 | 0 / completed | 0 / 5 / 0 | 0 |

每轮 records_read/footer/records_committed=5、五文件任务、日 completed、输入 enumeration_sealed=1，run 来源均为 dg_raw_parquet。取消不回退已完成日或成功文件，续跑重新枚举并复用首份。真实五次 GET 均 200/application/pdf，无额外探测/重试/重定向，最短请求结束至下一开始 5.119 秒，包含中断后重启间隔。新五份共 925,599 字节，Content-Length 与接收大小一致；旧五份与新五份共十次物理 size/hash 读回均匹配台账，两个台账 integrity_check=ok。

临时观察脚本初次把日状态 completed 误断言为 complete，产品命令实际已成功、五份跳过、零请求；原日志保留，修正观察断言后重复零请求验证，未改产品代码或重置台账。该观察错误不记为产品失败。详细进度间隔、取消响应耗时及各轮日期/哈希见机器报告。

本轮没有删除既有 PDF、备份/重建台账、修改默认台账、写 Prod/Lake、触发 DG job/事件/调度或安装依赖。删除后重下仍由隔离测试覆盖；现场删除须明确授权。现场拔盘、多域名/大文件、全量预算和 DG 连续日常稳定性不在本节证据内。产品代码没有新增改动，原 129 项测试仍为提交前证据；本轮新增真实验收报告及两份原设计状态回写。下一步按方案设计台账查询/维护能力，再做数据中心设计稿、API 和页面，不由最小验收自动启动批量下载。

## 16. 台账查询与维护设计及验收约束（2026-10-05）

状态：本地 CLI 已实现，隔离与正式只读验收通过；交付证据见 §16.4。用户授权本阶段，且要求进入数据中心页面前停下；Figma 与产品细节讨论是下一阶段前提。本阶段不做数据中心页面、API 或 Figma，也不创建公告业务数据库/搜索索引。

### 16.1 入口与范围

新增 `src/scripts/announcement_ledger.py` 和 `announcement_download/maintenance.py`。原 download_announcements 的入口/四参数/下载行为保留。所有子命令输出 JSON，可直接在终端查询，无需手工找 SQLite 文件。全局 `--output-root` 沿用 `/Volumes/datasource/announcements`；卷 UUID+卷内路径派生台账位置不变，不允许输入任意台账路径绕过身份。

| 命令 | 输入 | 输出/行为 |
| --- | --- | --- |
| summary | 归档根 | 实际台账路径、schema、文件状态/日期计数、来源映射及缺 URL 数、最近运行；不声称文件物理有效 |
| runs | limit、before-rowid，可选 run-id | 最近创建的运行或单次运行；实际记录的来源/范围/阶段/计数/原因；schema 1 标为历史 Prod，只观察不升级 |
| files | start/end-date、ts-code、title、state、run-id、limit、after-key | 参数化条件，稳定 artifact_key 游标，返回 path/state/error/size/hash/attempts；物理状态默认未检查 |
| show | artifact-key、limit | 单文件及关联来源 metadata、首次/末次运行，有界来源 rowid 游标；metadata 保留 NULL/空串 |
| verify | artifact-key | 只读检查 final 和 prepared part，不创建目录或更新台账，报告 matched/missing/mismatch/unallocated/untracked；不足以成功确认时退出 1 |
| repair | 必须 artifact-key | 明确单文件、排他归档锁，原 allocate/recover；返回前后事实及建议的原日期重下载参数，不发 HTTP |

show 的来源分页用可选 after-rowid，不无限拉全量来源。runs 的 before-rowid 及 files 的 after-key 均为当前台账观察游标，不代表冻结快照或业务身份；默认 20、最多 100，SQL LIMIT 为 limit+1。不新增 schema/index；首次发布对既有最大台账做有限只读计时，超预算阻断而非扩大超时或自动建索引。

### 16.2 配置项审计

| 配置 | 默认/来源/持久化 | 作用/消费者/依赖 | 生效/可见性/门禁 |
| --- | --- | --- | --- |
| output-root | 原默认归档根；新 CLI 参数，无新持久化 | 只读卷或写入 Volume、派生 Ledger；依赖卷 UUID/相对目录 | 每次启动，JSON 输出实际根/台账；错卷/禁止 Lake/符号链接/根不存在反例 |
| limit | 20；新 CLI 参数，LedgerQueryPolicy.page_default | 查询 runs/files/show，范围 1..100 | 本次查询，输出 limit/has_more/cursor；越界反例 |
| page_max | 100；LedgerQueryPolicy，无 env/DB 持久化 | 参数解析/查询，有界返回 | 启动，输出 policy；不得 fetchall/OFFSET |
| query_timeout_seconds | 4 秒；LedgerQueryPolicy，无 env/DB 持久化 | SQLite progress handler，整次只读观察事务共享截止时间；不冒用源读取 timeout | 每次命令，JSON policy；长 SQL 超时/Ctrl+C 反例 |
| sql_progress_steps | 1000；LedgerQueryPolicy，无 env/DB 持久化 | progress handler 回调步数，依赖 timeout/control | 每次 SQL，JSON policy；回调清理、后续查询可用 |

其他空间、哈希 chunk/max PDF、文件命名、卷检查预算沿用 DownloadPolicy 和原消费者。SQLite busy timeout 沿用 5 秒。没有下载间隔/来源根参数、配置数据库或新运行表，不修改已有下载 policy 摘要。

### 16.3 实现硬约束与代码/测试映射

| 约束 | 代码点 | 正/负验收 |
| --- | --- | --- |
| L1 查询完全只读 | Ledger(read_only=True)、SourceVolume+归档路径校验、LedgerQuery | schema 1/2 查询成功且字节不变；未创建/迁移/探测写、错身份/不存在/未知 schema 阻断 |
| L2 分页/参数/取消有界 | LedgerQueryPolicy/SQL wrapper/parser | 20/100/101+分页、参数化引号/通配符、空值、坏日期/cursor/state；真实长 SQL 超时与 Ctrl+C；不用 fetchall/OFFSET |
| L3 账面与物理明确区分 | files/show、verify、Files.fingerprint | succeeded 被删除仍显示账面 succeeded；verify 报 missing 且不改账；大小/hash错误、硬链接/符号链接/FIFO/路径越界阻断 |
| L4 单文件修复沿用协议 | repair、Volume 排他锁、Files.allocate/recover、Ledger.state | prepared 两窗口、缺失 pending、损坏文件保留/新路径、失败重试；成功文件不重下，wrong卷/锁冲突/无目标不写 |
| L5 历史与网络不受维护污染 | repair before/after、既有 Ledger | 不改 run/run_artifacts/source_records/cooldown/attempts，不取消旧 run；异常/取消已提交文件保留；零 HTTP/DG/Prod/Lake 写 |
| L6 产品阶段停止线 | 两份原文档、目录/引用审计 | 只改脚本/台账/测试；不进入数据中心 API/页面/Figma 或新增依赖 |

repair 先只读核验既有台账/目标与外盘，才使用原 Volume 的可写检查与排他锁，并在锁内再次读取目标，避免查询后下载改变状态。只升级已识别且已有的旧台账，不创建空归档；缺目标在写门禁前退出。prepared 的 final/part 无法匹配时沿用 prepared_evidence_mismatch，保留文件、标为 failed，可由下一次原日期下载命令重新开始；不强行提升不明文件。历史 run/task outcomes 保留为当时事实，不按修复后的 artifact 状态重写计数；不将下载历史标成当前物理清单。

只读模式不拿写锁、不需要 DG Raw/DuckDB/数据库/网络可用，不读正式 Lake；各命令只访问选择归档及其自动派生台账。来源详情保留原 JSON 值，不用 title/name/rec_time 推断另一身份。文件指纹必须以 O_NOFOLLOW|O_NONBLOCK 打开并核实 regular/nlink/device，不允许 FIFO 阻塞取消。SQLite 原 DELETE journal 与写入 busy timeout=5 秒不变：查询同一只读事务总预算为 4 秒，每个 SQL 检查共享截止时间，事务在卷复检/打印/文件哈希之前关闭，减少干扰下载提交；预算耗尽应重新发起窄查询，不在同一过期事务继续。repair 不持覆盖范围的事务，逐步提交遵循原 prepared 协议。

实际验收只读 default schema 1 的概况/有界文件与单条物理校验、独立 schema 2 的五文件校验；维护故障注入全部用临时目录，不删除正式验收文件。验证完成后回写本节交付状态与证据；数据中心下一阶段必须停止，等待产品细节/Figma 完成后的明确授权。

### 16.4 实施、使用与停止线

新增 [台账入口](../../src/scripts/announcement_ledger.py)、[查询/单文件维护](../../src/foundation/dao/announcement_archive/maintenance.py)和[维护专项](../../tests/test_announcement_ledger.py)；Ledger 增加只读打开分支、Volume 提取同一归档禁止路径校验，Files.fingerprint 增加非阻塞打开/同设备核验，原下载入口及 schema 2 不变。故障恢复调用原 Files.allocate/recover，不复制一套文件提升协议。

在仓库根目录使用现有环境。示例 KEY 必须替换为 files 返回的完整 artifact_key；以下查询默认归档，`--output-root` 可在子命令前选择其他已有归档根：

```bash
.venv/bin/python -m src.scripts.announcement_ledger summary
.venv/bin/python -m src.scripts.announcement_ledger runs --limit 5
.venv/bin/python -m src.scripts.announcement_ledger files --start-date 2026-09-01 --end-date 2026-09-30 --state failed --limit 20
.venv/bin/python -m src.scripts.announcement_ledger files --ts-code 600000.SH --title 年报 --limit 20
.venv/bin/python -m src.scripts.announcement_ledger show --artifact-key KEY
.venv/bin/python -m src.scripts.announcement_ledger verify --artifact-key KEY
.venv/bin/python -m src.scripts.announcement_ledger repair --artifact-key KEY
```

files 继续翻页传 next_after_key 为 --after-key；runs 传 next_before_rowid 为 --before-rowid；show 传 sources.next_after_rowid 为 --after-rowid。has_more=false 时结束。verify/repair 必须明确单个 key，不能按一段日期批量修改台账。查询和 verify 不需要 DG Raw、DuckDB、PG/CH 或网站在线。

repair 不请求 PDF，返回前后状态和 redownload 日期/输出根参数；ready_for_download 表示台账已整理为 pending。执行原下载命令仍会重新枚举这一完整自然日，同日其他未完成文件也会下载，有效成功文件跳过；这不是单 URL 立即下载入口，必须有对应 DG 日文件。若只删除一份且其他当日文件有效，验证证明仅重下缺失这一份。failed 表示现场 prepared 证据等不满足提升规则；不会强行宣告成功或删除证据。

退出码：0 查询/物理匹配/修复成功；1 verify 无法匹配 final 或 repair 文件失败；2 参数错误；3 台账/卷/SQL/锁等阻断；130 用户 Ctrl+C。历史 runs/run_artifacts/source_records/cooldown 与 attempts 不因 repair 重写；因此历史 run 可以 completed，而当前某文件已缺失，必须以 verify 输出区分账面/物理事实。repair 可能原子升级已识别的 schema 1；只读命令绝不升级。

[验收报告](../../reports/anns_d_ledger_maintenance_acceptance_20261005.md)、[机器证据](../../reports/anns_d_ledger_maintenance_acceptance_20261005.json)记录正式 schema 1 默认台账和 schema 2 独立验收台账的 16 次只读 CLI 调用，六份 PDF size/hash 匹配，两份 SQLite 前后 SHA-256 相同，未在正式目录 repair/删除/重下。默认台账 34,188 条文件/来源映射，有界查询及概况均在 4 秒 SQL 观察预算内；完整 CLI 耗时包含外盘检查，逐轮见报告，不外推全历史台账性能。

实施前 CodeGraph explore/search 复核 Ledger、Volume、Files 与原 CLI 关系，通用名命中其他同名组件，补读真实目录源码/SQL/专项消费者；实现后 sync/status 核验索引。无前端/API 消费者修改，无 DatasetDefinition、DG 合同/同步、Ops TaskRun 或子系统依赖变化。校验数量以验收报告为准；每条 L1—L6 均有对应代码/测试/只读或目录范围证据。现场修复写入与真实拔盘未执行，相关故障路径仅隔离证明。

**2026-10-05台账阶段按用户要求在此停下，未开展页面/API/Figma。此为历史阶段边界；2026-10-06产品/Figma R1已确认，现已获准编写网页技术方案与LLD，见§17；页面/API仍未编码。**

## 17. 网页产品化合同引用（2026-10-06；设计稿）

[数据中心技术方案](../../wealth/docs/pages/data-center/data-center-announcements-implementation-design-v1.md)与[网页LLD](../../wealth/docs/pages/data-center/data-center-announcements-low-level-design-v1.md)完整规定公告查询、日期预览、后台运行、停止/继续、精确失败重试、历史、部署差异及Figma24状态。它们是**未来网页扩展**的合同；本文件§1—§16保留schema2/CLI的历史基线；最新DC1基础实现见§18，正式台账未升级。

网页目标迁移完整消费链：download/ledger两个CLI、Source、Ledger、Files、HTTP、maintenance、旧schema fixture及全部公告测试。主实现移出工具目录，保留单一身份/卷门禁/限速/文件提交协议，清零旧import而不新增转发兼容包。schema3新增预览关联、控制/会话/尝试/进度和幂等事实，但保留schema1/2只读识别及原历史数据，不清空/改归档身份。原CLI日期重放保留；网页continue只恢复sealed原集合，retry另建原失败集合的关联批次，不能扩大到同日或同公司其它文件。

网页查询只用成功台账加安全文件存在性判断，不套用CLI verify的逐文件hash；完整公告目录来自按日期可重建的DG投影，不是source_records下载子集。原CLI repair/verify继续独立存在，不因此新增网页维护按钮、本地PDF服务或DG同步入口。

新增配置、schema、端口/API、状态机、SQL、迁移回归、业务/观察事务隔离和真实验收由网页LLD统一定义，本文件不复制第二套字段合同。本轮没有执行迁移/下载/索引写入；依赖矩阵不改，后续实施按网页DC阶段授权。

## 18. DC1实施后的历史入口（2026-10-06）

当前链路 `download_announcements.main → Ops executor.run_cli/execute → Foundation Source/Volume/Files/Downloader/DAO Ledger(schema3)`；台账入口 `announcement_ledger.main → Ops maintenance.run_cli → DAO LedgerQuery / Files.verify_one / Ops repair_one`。旧src/scripts/announcement_download主实现包已删除，旧路径只存在于历史叙述/报告中。CLI参数/退出行为保持，输出中的schema_version反映实际1/2/3。

单写schema3；schema1→3的所有DDL含原1→2部分在同一事务，不存在中间独立提交；schema2同样原子增量到3。只读CLI支持1/2/3不写、不建、不升。调用方持本机execution.lock→外盘archive.lock后才打开写台账；DAO不代替卷门禁或自己取得物理锁。旧事实保留、不备份/清空/重建，未知/损坏schema阻断。只有临时隔离账本升级，正式默认/验收台账未打开升级。

身份/Raw reader逐字节不变；代表标题只在新artifact封存前确定，不重命名旧文件。新增控制slot/session/attempt/receipt及进度字段，已完成run结果不可覆盖；进程退出/观察写失败保留PDF和尝试证据，显式新日期命令可以复用文件。网页原run继续和关联失败批次仍属于DC3，不由CLI日期重放冒充。

[DC1验收报告](../../reports/wealth_data_center_dc1_acceptance_20261006.md)及[机器证据](../../reports/wealth_data_center_dc1_acceptance_20261006.json)：完整387项、最终受影响217项通过，ingestion lint/compileall/CLI help通过；正式Raw五条只读指纹一致，无台账打开/来源写入/PDF请求。依赖矩阵不改，CodeGraph sync/status为up to date；新增pypinyin0.55.0为获准本地可选依赖，名称索引消费者在DC2实现。源站多域名真实归档、实际拔盘、容量预算、网页和正式迁移继续按后续阶段验证。


## 19. Q3 PG 运行存储、CLI 与维护合同（2026-10-07）

### 19.1 配置、结构与生命周期

使用原[数据中心 LLD §22.5—22.6](../../wealth/docs/pages/data-center/data-center-announcements-low-level-design-v1.md)的配置和DDL，不增加新配置。`ANNOUNCEMENT_ARCHIVE_DATABASE_URL` 默认空，只接受 `postgresql+psycopg`、loopback、5432和`goldenshare_lake_meta`，固定schema `announcement_archive`；没有主库回退、SQL兼容壳或双存储开关。Web独立archive连接池由App持有，查询和执行共用；CLI创建自己的同策略池，退出时释放。未配置或PG/schema不可用时明确阻断。

`Ledger(database, volume_uuid, relative_root)`读取并校验PG结构和archive；`initialize=True`仅在已通过写卷门禁的下载资源工厂使用，允许登记native archive/cooldown/execution，不执行DDL。只读查询、summary、history和context不初始化archive。PG schema版本1与迁移来源SQLite版本2/3是不同概念，迁移原版本保存在`source_schema_version`，不会影响JSON的PG schemaVersion。

`ArchiveStore`只建立短期DAO，读写不跨文件hash或HTTP持有数据库事务。`archive_execution`行锁协调领取，保留本机`execution.lock`与外盘`.state/archive.lock`；`begin_run/claim`在一个短事务内创建/领取任务、会话和receipt。恢复弃置状态仅在已取得本机执行锁的显式执行/恢复入口进行，打开Ledger不会自动续跑HTTP，也不按心跳超时抢占。

### 19.2 文件、HTTP 与观测隔离

既有 `Files` 与 `Downloader` 的提交顺序保留：接收块→fsync part→PG prepared提交→os.replace→目录fsync→PG succeeded→单文件run结果。任何窗口退出都保留已提交事实/文件，sealed run的继续仅取outcome为空的文件；failed重试建立原失败key集合的关联run，原run结果与原因不改写。

所有表和子查询显式带archive_id，JOIN按archive_id+artifact_key。单批最多500，日记录/计数同事务；完整日期/footer/指纹核对后seal。重复result不重复计数，cooldown使用PG `greatest`，跨进程不可缩短。恢复prepared或完整PDF不再次发HTTP；已删除成功文件仍可重新下载。

WebControl在每个业务检查点读取持久停止/owner，后台停止观察间隔0.5秒，进度/心跳默认5秒；观测失败不回滚/阻断文件业务提交，每次观测失败也节流。PG业务写失败阻断执行，`request_started`必须在每个HTTP前独立成功提交，PG只读或离线时零新请求。PG恢复后仍需用户显式继续，不自动发HTTP。

LedgerQuery使用PG原生参数化SQL和4秒整体预算，按剩余时间设置statement_timeout；Ctrl+C取消当前驱动查询，随后事务回滚/连接归还，不保留读事务跨文件核验。文本标题用strpos按原文字面匹配，百分号/下划线不作通配符。列表最多100，分页仍传正整数旧参数，SQL使用row_seq。

### 19.3 命令与JSON（Q4迁移/启用完成后使用）

```bash
GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -m src.scripts.download_announcements \
  --start-date 2026-09-30 --end-date 2026-09-30 --interval-seconds 5

GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -m src.scripts.announcement_ledger summary
GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -m src.scripts.announcement_ledger runs --limit 20 --before-rowid 123
GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -m src.scripts.announcement_ledger files --ts-code 002245.SZ --title 公告
GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -m src.scripts.announcement_ledger show --artifact-key KEY --after-rowid 123
GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -m src.scripts.announcement_ledger verify --artifact-key KEY
GOLDENSHARE_ENV_FILE=.env.web.local .venv/bin/python -m src.scripts.announcement_ledger repair --artifact-key KEY
```

默认output-root仍为`/Volumes/datasource/announcements`；需要指定时位于台账子命令前。日期命令重放重新枚举该日期范围，有效文件复用；Web continue保留原sealed集合，retry仅原失败集合，不混淆两者。verify只核验本地文件；repair整理或恢复prepared，不联网、不删除已存在文件、不自动升级结构。维护命令不依赖DG/CH，但依赖已初始化的PG及已验证输出卷。

正常JSON包含：

```json
{"storage":{"kind":"postgresql","database":"goldenshare_lake_meta","schema":"announcement_archive","archiveId":"归档身份哈希","schemaVersion":1}}
```

没有`ledger_path`或顶层`schema_version`。runs/show的`next_before_rowid/next_after_rowid`仍是整数，回传到同名旧CLI参数；导入旧rowid时保留row_seq。原参数错误/启动阻断/文件失败/取消退出码不变，详细测试与实测见Q3报告。正式库、环境与原SQLite尚未操作；下一阶段Q4先PLAN、显式APPLY、读回再切换，文件清理单独批准。


### 19.4 Q4 正式启用记录（2026-10-07）

Q3已提交b4c590fd。Q4已按网页LLD§26执行4份旧台账迁移、完整值重放/读回和统一PG启用；默认363个成功文件及三验收根各5个文件的size/hash全部匹配。只在既有.env.web.local写入独立本地DSN，Web8000已恢复；下载/维护CLI须按§19.3指定同一GOLDENSHARE_ENV_FILE。独立日期验收5条/5文件全部复用，源站请求0；未自动全量下载、未清理旧文件。

迁移工具增加互斥--cleanup-plan（只读清单）和--cleanup（独立获准后删除精确旧文件）。不在下载/查询命令启动时迁移或清理，不卸载共享SQLite。实际清单及下一步批准边界见[Q4报告](../../reports/wealth_data_center_q4_acceptance_20261007.md)。
