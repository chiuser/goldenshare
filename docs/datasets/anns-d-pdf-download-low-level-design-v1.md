# 上市公司公告 PDF 本地归档 LLD v1

更新时间：2026-10-01。状态：设计待评审、尚未实现。需求和范围以[技术方案](/Users/congming/github/goldenshare/docs/datasets/anns-d-pdf-download-technical-plan-v1.md)为准；本文给出可实施、可测试的细节，不预填开发或真实验收结果。

## 1. 改动范围与依赖

拟新增：

| 位置 | 职责 |
| --- | --- |
| `src/scripts/download_announcements.py` | argparse 入口、参数校验、信号取消、阶段输出与流程组合 |
| `src/scripts/announcement_download/volume.py` | 外部卷识别、句柄固定、空间和可写探针、运行期卷核验 |
| `src/scripts/announcement_download/source.py` | 指定 Raw 表的只读、有界枚举 |
| `src/scripts/announcement_download/ledger.py` | 本地 SQLite、归档锁、行映射、冷却与文件状态 |
| `src/scripts/announcement_download/files.py` | 安全命名、流式暂存、校验与原子提交/恢复 |
| `src/scripts/announcement_download/http.py` | 串行请求、手动重定向、可取消限速、有限重试 |
| `tests/test_announcement_download_*.py` | 隔离测试与故障注入，不默认连接 Prod 或写外盘 |

模块目录及 `__init__.py` 是拟新增工具实现，不新增业务子系统。工具可引用现有 Foundation 定义、Settings 和底层数据库依赖，不从 Foundation 反向导入工具。不改 `src/cli.py` 注册、不引入 Ops runtime，不改模型、DatasetDefinition、request builder 或 Alembic。实现时如发现必须改变这些边界，暂停并修订设计。

使用已声明依赖 SQLAlchemy、psycopg、httpx，以及标准库 argparse/sqlite3/hashlib/subprocess/plistlib；macOS `diskutil` 为系统工具。依赖声明不证明本机已安装，M1 前检查现有环境，不自动安装或同步依赖。

## 2. 参数与配置项审计

命令行参数统一解析为不可变 `DownloadOptions`，消费者不能各自另设默认值。表中新增工程默认值在实现中只能集中定义一次。

| 名称 | 默认/校验 | 来源、持久化 | 全部消费者与作用域 | 生效/可见性/测试 |
| --- | --- | --- | --- | --- |
| `--start-date` | 必填，ISO `YYYY-MM-DD` | CLI；runs 保存实际值 | source 日期下界；progress 展示本轮范围 | 启动；非法日期、边界反例 |
| `--end-date` | 必填，ISO 日期，必须 ≥ start | CLI；runs 保存实际值 | source 日期上界；progress 展示 | 启动；闭区间测试 |
| `--interval-seconds` | 5.0；有限非负数，支持小数与 0 | CLI；runs 保存实际值 | HTTP 全部请求、retry、redirect；progress 展示 | 下次启动可修改；fake clock 测试 |
| `--output-root` | `/Volumes/datasource/announcements` | CLI；账本记录卷 UUID 与规范路径 | volume、ledger、files、progress | 启动；外卷、路径越界、符号链接反例 |
| `GOLDENSHARE_ENV_FILE` | 沿用 Settings 的 `.env` 默认 | 已有 env；只保存脱敏来源标识 | 现有 Settings、source | 启动；文件存在/实际值来源测试 |
| `DATABASE_URL` | 必须有显式值，不使用 Settings 默认 localhost URL | 现有 env/配置文件；不在账本保存凭据 | source 的独立只读 engine | 启动；缺失、配置优先级、脱敏测试 |
| 本地账本位置（自动派生） | `~/Library/Application Support/Goldenshare/announcement-download/<归档身份>/downloads.sqlite` | 单一 options factory 由卷 UUID + 卷内相对目录生成；本机持久化，无新增 env/CLI | ledger、启动恢复；按归档身份隔离 | 启动；同卷重挂载复用、不同卷隔离、目录可写测试 |

现有 [Settings](/Users/congming/github/goldenshare/src/foundation/config/settings.py)中环境文件值优先于同名进程 env，工具必须沿用并在测试中证明，不在 source 另行解析出一套相反优先级。只保存环境文件路径及无密码的连接目标摘要；不打印 URL query 或认证信息。

以下为统一 `DownloadPolicy` 工程限制，第一版不另暴露为用户参数；需修改时同步两份原设计：

| 策略 | 设计值 | 消费者与测试 |
| --- | --- | --- |
| 并发 | 1；同归档根单进程锁 | HTTP/ledger；跨进程互斥 |
| DB 批次/超时 | 500 行 / 每次 15 秒 | source；游标与超时测试 |
| 流块大小 | 64 KiB | files；不累积正文测试 |
| 最大 PDF / 磁盘安全余量 | 512 MiB / 1 GiB | files/volume；header、流式计数、空间反例 |
| 网络超时 | connect 10s、read 15s、write 15s、pool 5s；单次文件传输硬期限 10 分钟 | HTTP；慢流和取消测试，期限不含冷却 |
| 单文件请求尝试 | 最多 3 次，含首次；每次最多 5 跳重定向 | HTTP/ledger；次数与循环反例 |
| 退避 | 初次 30s，随后 60s；服务器要求优先 | limiter；Retry-After 两种格式和时钟测试 |
| 标题文件名预算 | 完整 basename ≤ 200 UTF-8 字节，包含后缀和 `.pdf` | files；中文、碰撞、截断测试 |
| 进度/取消检查 | 更新 ≤ 5s；等待分片 ≤ 0.5s | runner/HTTP；等待中取消测试 |

512 MiB 是限制而非已测公告大小；超限记 `file_too_large`，不能截断后宣称成功。每个文件开始前要求可用空间 ≥ 安全余量 + 单文件上限；流式过程中也检查空间。全量容量仍须按真实样本估计。

## 3. 外盘门禁和文件操作顺序

1. 解析参数；拒绝非法日期/间隔，不连接数据库、不创建目标目录。
2. 沿目标路径找到真实存在的外部卷挂载点。用现有 `diskutil info -plist` 核对 UUID、Mounted、Writable、介质外部属性及物理设备；APFS 容器追溯 physical store，所需信息无法取得就失败。
3. 排除系统卷、内部物理盘、普通本地目录、虚拟映像及无法确定外部介质的目标。第一版 macOS 专用，不对其他平台静默降级。
4. 逐层拒绝符号链接，确认目标在该卷内且不属于 DG Lake/staging/退役 Lake 路径。`/Volumes/datasource` 只是候选路径，名字本身不是证据。
5. 固定卷 UUID、设备号和卷目录 fd。目录创建、打开、rename、删除探针等使用 `dir_fd` 相对操作和 `O_NOFOLLOW`；只在已固定卷上创建缺失子目录。
6. 核对空间；用随机且排他创建的本工具探针测试写入与 fsync，移除自身探针，不能清理外部目录。文件和目录同步不支持时停止，不能静默降为不可靠提交。
7. 在固定外盘目录句柄下创建 `.state/archive.lock` 并取得 `flock`，再打开本机 Application Support 下派生的 SQLite；本机账本目录不可写就退出。采用 DELETE journal、`synchronous=FULL`。SQLite 使用本机路径，不能声称标准 sqlite3 支持任意 `dir_fd` 或依靠重新检查绝对挂载路径消除竞态。锁文件可以保留；以 OS 锁而不是文件存在判断占用。
8. 此后才建立数据库连接。所有存储写入与每次外部请求前核验 UUID/设备/挂载状态；旧 fd 不得改用系统盘路径重开。

拔盘后外盘 fsync/rename 失败统一中止，尽可能将中断原因保存至本机账本；允许保留 `.part` 和可读的已完成成果。进程无法写本机账本时，终端明确最后一个已确认文件，不能伪报本轮全部完成。目录句柄方案与实际磁盘文件系统兼容性必须通过 M3，文档不宣称跨任意文件系统的掉电原子性。

## 4. 数据库只读枚举

source 从当前 Definition 校验 Raw 表映射仍为 `raw_tushare.anns_d`、日期字段仍为 `ann_date`；不另建 dataset registry。变化时明确失败，不能猜列或自动切别的表。

白名单投影：`id, row_key_hash, ann_date, ts_code, title, url, rec_time`。不读 `raw_payload`，不 `SELECT *`，不使用 DAO 的写方法。每批独立事务，首先设置 READ ONLY，再设置 statement_timeout。

本轮开始用主键降序 `LIMIT 1` 获得 `upper_id`，从 `after_id=0` 枚举：

```sql
SELECT id, row_key_hash, ann_date, ts_code, title, url, rec_time
FROM raw_tushare.anns_d
WHERE ann_date >= :start_date AND ann_date <= :end_date
  AND id > :after_id AND id <= :upper_id
ORDER BY id
LIMIT :batch_size;
```

全部绑定参数。每批将行映射、下载身份和 `after_id=max(id)` 在同一个本地 SQLite 事务提交；空页标记枚举结束。只读 DB 事务在本地落账前关闭，不跨 HTTP 传输或整个历史范围持有事务。批次失败不推进本地游标。

新命令创建新 run，重新枚举同一日期，因此不因旧 high watermark 漏掉新入库记录。下载账本跨 run 复用，旧枚举无需续扫才能保证文件任务续跑。`upper_id` 仅限制本轮读取范围，不保证数据库一致快照；并发事务较晚提交或旧行更新应在下一次重扫纳入。必要时等公告元数据更新完成再启动，不能以一次枚举结果宣称同步完整。

真实查询计划待验证，LIMIT 只限制返回行数。M1/M3 前在窄日期和宽日期分别 EXPLAIN，确认访问路径、耗时与排序开销；若不能满足 15 秒或内存界限，调整批读设计并回写本文，不自行加生产索引、扩大超时或改数据库。

## 5. 本地身份与账本

`artifact_key = sha256(规范 JSON 数组 [ann_date.isoformat(), ts_code, url.strip()])`，使用明确 UTF-8 编码与固定序列化。它是本地文件任务身份，不替代 `row_key_hash`。同 URL 跨日期或跨公司分别归档，不自动跨目录复制、硬链接或全盘去重。

SQLite 设计表：

| 表 | 关键字段及约束 |
| --- | --- |
| archive | 单行 schema_version、volume_uuid、root_relative_path、created_at |
| runs | run_id、日期范围、间隔、脱敏来源、upper_id、after_id、阶段、计数、终态、更新时间 |
| source_records | source_scope + row_key_hash 唯一；raw_id、完整元数据、artifact_key、first_seen/last_seen_run |
| artifacts | artifact_key 主键；原始 URL、首次标题、已分配相对文件路径、状态、错误、attempts、size、sha256、更新时间 |
| run_artifacts | run_id + artifact_key 唯一；本轮结果和尝试量，限定本轮范围 |
| cooldown | 单行 last_request_finished_at、next_request_not_before UTC、request_in_flight、原因；请求开始和结束分别落账 |

source_scope 来自脱敏数据库目标及固定 schema/table，不能仅凭 row_key_hash 混合不同来源。source_records 保留同文件的全部行映射。路径分配使用 NFC + casefold 唯一键处理大小写不敏感卷，原始文件名保留中文。

states：`pending → downloading → prepared → succeeded`；可转 `failed / blocked`。run 为 `enumerating / downloading / completed / partial_failed / cancelled / blocked`。终态不能由进程退出码反推，必须基于本轮结果。

启动取得独占锁后，将遗留的非终态 run 记为 cancelled，原因 `process_exit_recovered`，再创建新 run。保留旧计数和游标，文件状态按恢复矩阵核验；不能把进程崩溃记为 completed。

attempts 累计历史次数与本轮尝试数分开保存；每轮最多 3 次，不因历史失败永久禁用重试。下一次命令对本轮重新出现的 failed/blocked 项允许重试，但必须遵守持久化冷却；不领取所选日期外的旧任务。

## 6. 文件名、校验和原子提交

先以清洗后的 `title.pdf` 分配路径；同名任务、现有未知文件或大小写等价名称占用时，追加 artifact_key 前 12 位，仍冲突则逐级延长至完整 hash；仍被占用时失败。路径分配必须落账后再开始下载，不能因数据库返回顺序改变已分配路径。

标题为空或代码/日期/URL 不合法，记明确错误，不创建文件。URL 只接受 HTTP/HTTPS，不接受本地 file URL；TLS 验证开启，不伪造 Referer。实际站点需要额外请求头或认证时先报告证据、修订方案。

下载步骤：

1. 校验目标卷、空间和已分配路径；创建同目录专属 `<basename>.<artifact_key>.part`。仅处理账本归属本工具的暂存文件。
2. 响应流块大小 64 KiB；累计 size 和 SHA-256，不把整份正文放进内存。
3. 检查成功状态、开头允许 PDF 版本标记、Content-Type 未明确为 HTML、长度未超限、可用 Content-Length 与传输字节一致、末尾基本 `%%EOF` 标记。强制 identity 传输编码以便长度对账；仍返回压缩编码时拒绝并记录原因，不混用解码后长度。
4. fsync `.part`，保存 prepared 的 size/sha256；再次校验卷与最终路径，禁止覆盖非本任务文件；同根独占锁保证本工具无并行提交。
5. `os.replace()` 提升并同步父目录，提交 succeeded。SQLite 成功保存前不能报告成功。

自动恢复矩阵：

| 中断位置 | 重启行为 |
| --- | --- |
| downloading，只有不完整 part | 从头重下本文件，保留其他成功文件 |
| prepared，part 完整、final 不存在 | 核对记录的 size/hash 后完成提升，不再发 HTTP |
| prepared，final 存在且 size/hash 一致 | 补记成功；此为 rename 后账本提交前恢复 |
| succeeded，final 校验一致 | 本轮 skipped，不发 HTTP |
| succeeded，final 缺失 | 回到 pending，重新下载 |
| final 损坏或未知文件占用路径 | 分配新的安全路径并落账后重下，保留原文件、不覆盖 |
| final 和 part 均无法与 prepared 对上 | 记录恢复失败，保留证据，不猜测成功 |

SQLite 与文件系统无法组成同一个事务，因此必须保留 prepared 恢复协议。文件校验保证基础格式和传输一致，不保证内容真实性、可阅读性或网站后来未修改相同 URL。成功文件不会每轮重新联网探测远端版本，URL 内容修订另行处理。

## 7. 限速、重试和取消

全局单请求调度器，上一请求结束后计算下一可请求时间；UTC 截止时间持久化，运行期使用 monotonic 等待。进程重启取 `max(持久化截止时间, last_request_finished_at + 本轮 interval)`，不能通过改小间隔缩短已记录冷却。遗留 request_in_flight 表示结束时间未知，重启后至少再等待本轮 interval；已知的较晚服务器冷却仍保留。请求开始前先落 in-flight，失败不能发请求；请求结束后无法落账就停止，不继续领取文件。HTTP transport 禁用隐式重试，由统一调度器控制全部尝试。

关闭 httpx 自动重定向。301/302/303/307/308 按 Location 显式发起下一请求，每跳先限速、检查取消、重新核验卷；最多 5 跳，禁止循环和 HTTPS 降级 HTTP。相对 Location 依据实际响应 URL 解析，不猜域名。

- 超时、连接错误、408、429、5xx：按最多 3 次尝试处理，退避从 30 秒开始；不得立即密集重试。
- Retry-After：支持秒数和 HTTP date；过去值按 0 处理，实际等待仍不低于 interval/退避。对 429 以及携带此头的 503 遵守要求，不截短服务器等待；长等待可以取消。
- 403、验证码/明确拦截：本轮 blocked，停止全部后续请求，保留拒绝原因和状态。
- 404/410、非法重定向、非 PDF：当前文件 failed，下一文件仍按间隔调度。
- 外盘/SQLite/锁/配置/数据库错误：本轮 blocked，停止领取新任务。

每次实际请求开始/结束、传输块、等待分片、枚举批次前后及原子提交前检查取消。Ctrl+C 停止新请求；尚未提交文件留暂存状态，已提交文件不回滚。等待以 ≤0.5 秒分片处理，网络 read timeout 15 秒；不能承诺取消瞬间终止正在阻塞的系统调用，但需在可控边界内退出。

## 8. 进度、错误和退出码

枚举阶段显示读取行数、已归入文件数、游标和范围，不伪造总量百分比。枚举完成后以 run_artifacts 为分母，显示当前标题/公司、完成量、成功/跳过/失败数量、百分比与更新时间。记录数与唯一文件数分别显示。

下载、校验和等待中每 5 秒输出进度；ETA 未有可靠样本时显示“暂无法估算”。输出不含密码、完整敏感 query 或错误页正文。错误保留 reason code、HTTP status、脱敏 host、尝试数，URL 原值仅在本地账本用于追溯。

退出码：0=本轮全部文件成功或有效跳过（空范围也显示 0 个记录）；1=本轮存在文件失败；2=参数或环境/磁盘门禁失败；3=运行被阻断；130=用户取消。不得仅打印错误仍返回 0。

## 9. 硬要求与验收映射

以下全部是待实施测试，不能当成已有 PASS。

| 要求 | 实现位置 | 正向测试 | 反例/故障测试 |
| --- | --- | --- | --- |
| R1 本地入口 | CLI、options | 指定和默认路径解析 | 缺显式 DB 配置，不能回落 localhost |
| R2 日期闭区间 | source | 起止日都纳入 | 前后一天、逆序、非法日期、空范围 |
| R3 目录 | files | 日期/完整代码目录 | ../、控制字符、符号链接越界 |
| R4 标题命名 | files、ledger | 中文标题和长标题 | 同名不同 URL、NFC/casefold 碰撞、未知现有文件 |
| R5 间隔 | limiter、HTTP | fake clock 证明请求结束后间隔 | redirect/retry 绕过、负数/NaN/inf、冷却重启 |
| R6 续跑 | ledger、files | 重复命令已完成零请求 | 枚举崩溃、下载中断、prepared 前后、rename 后/成功落账前、SQLite 写失败 |
| R7 外盘门禁 | volume | 通过真实挂载证据后才创建子目录 | 目录存在但未挂载、内部盘、只读、空间不足、同名换盘、检查与写入间拔盘 |
| R8 新公告 | source、run_artifacts | 第二轮新增记录被纳入 | 历史游标误跳过、旧范围任务误执行、并发更新不能宣称一致快照 |
| 文件可靠性 | files | 完整 PDF、size/hash 读回 | HTTP 200 HTML、截断、超限、损坏、fsync 不支持 |
| 有界运行 | source、HTTP | 单批 500、流块 64KiB | 整范围驻留内存、慢流硬期限、长事务跨下载 |
| 观测和取消 | runner | 进度与终态一致 | 冷却中取消、数据库超时、403 后仍领取文件 |

M2 使用隔离临时目录、模拟卷元数据和本地 HTTP fixtures；启动本地服务需获工具层权限，测试不调用远端网站、不使用正式外盘/业务表。禁止以测试为由安装套件、删业务数据或清理用户目录。

M3 另获执行授权后，Prod 只读获取最多 5 个 URL，先按实际域名核验重定向、响应类型、大小与拦截行为，再在外盘执行下载—中断—续跑—校验。核对元数据记录数、去重任务数、请求数、请求时间戳、成功/跳过/失败数和物理文件 size/hash；请求次数要能解释到首次、重试、重定向，不能把文件数当作请求数。

## 10. 影响面与本轮验证记录

2026-10-01 使用仓库根 CodeGraph CLI：`status`（索引 up to date）、`query anns_d`、`query SessionLocal`、`impact RawAnnsD`、`callers RawAnnsD`、`callers _anns_d_params`、`callers SessionLocal`、`callees _anns_d_row_transform`。索引 impact 仅返回模型符号，动态 registry 调用未在 callers 完整呈现，不能当作消费者完整证明；补用当前代码搜索与逐项读取覆盖 Definition → request builder/row transform → Raw ORM/DAO → Serving view、Ops action_catalog、CLI、既有测试及 frontend/wealth/qtf/biz/app 消费者。直接前端/API 使用未在这次窄搜索中发现，不外推为不存在仓库外 SQL 消费者。

本轮仅新增两份设计文档并更新 docs 索引，未改变运行入口、契约、分层或依赖矩阵。后续实现保持当前 `dev-interface`，不建分支/worktree，不提交其他未完成工作。

待记录的实施证据：现有依赖检查、批读 EXPLAIN、真实 URL 最小样本、实际外卷/文件系统识别、rename/fsync/SQLite 故障恢复。当前没有需用户补充的功能选择；若真实证据要求新增认证、改变数据库、路径或依赖，按差异重新评审。
