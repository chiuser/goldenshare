# 上市公司公告 PDF 本地归档技术方案 v1

更新时间：2026-10-01。状态：设计待评审，尚未实现、未下载。用户已确认本地 CLI、日期范围、标题命名、可配置请求间隔、续跑和外部磁盘启动检查；本文中的工程默认值属于本次设计建议，不是既有实现。

## 1. 目标与依据

从已有 Prod `anns_d` 记录读取公告 URL，将 PDF 归档到本机外部磁盘。按公告日期 `ann_date`、上市公司代码 `ts_code` 建目录，以 `title` 生成文件名。相同命令重复执行能够继续未完成下载，并纳入随后更新的公告记录。

依据：

- 本次用户确认的需求及[根规则](/Users/congming/github/goldenshare/AGENTS.md)。
- [当前公告维护说明](/Users/congming/github/goldenshare/docs/datasets/anns-d-dataset-development.md)和[DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/news.py)。
- [Raw 模型](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_anns_d.py)、[读取模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/anns_d.py)、[归一化身份实现](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)。
- Tushare doc_id=176，[本地接口说明](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料/0176_上市公司全量公告.md)说明 URL 是原文下载链接；真实站点行为仍待验证。
- [子系统边界基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)、[日期消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)。

公告元数据维护仍使用既有 `anns_d.maintain` 主链。本工具只读取已经入库的记录、写本地 PDF，不调用 Tushare、不更新 Prod 数据集、不新增 DatasetDefinition 或 DatasetExecutionPlan。因此不复制 Prod 数据集开发模板，不创建 Ops TaskRun；本地下载账本只记录文件归档事实，不成为公告数据集事实源。

## 2. 当前事实与证据边界

| 项目 | 已核对事实 |
| --- | --- |
| 物理表 | `raw_tushare.anns_d`，自增 `id`、唯一 `row_key_hash` |
| 读取出口 | `core_serving_light.anns_d`，普通视图，不含 Raw `id` |
| 日期 | `ann_date` 是自然日公告日期；支持区间，不要求每天都有公告 |
| 行身份 | SHA-256 输入包含日期、代码、标题、URL、`rec_time` |
| 现有写入 | `RowKeyHashDAO.bulk_upsert` 以 hash 冲突更新，保留自增主键 |
| Prod 日期端点 | 北京时间 2026-10-01 15:31:08，只读查询得到 `2025-01-01`～`2026-09-30` |
| 端点查询 | 确认日期索引，正反向 Index Only Scan，各 `LIMIT 1`；不代表区间完整性 |

工具选用 Raw 显式投影，以 `id` 作为可恢复枚举游标。原因是需要有界读取和本地记录追溯；不改变其他消费者的 Serving 出口。只读事务、短查询和绑定参数是硬要求。

后续更新可能改变日期端点。下载范围只代表运行时读到的元数据，不证明 Tushare 全集已同步。实际 URL 域名、PDF 大小、限流规则、外盘文件系统和安装环境尚未验证。

## 3. 已确认的能力与边界

| 编号 | 必须支持的要求 |
| --- | --- |
| R1 | 本地 CLI 执行，默认目标 `/Volumes/datasource/announcements` |
| R2 | `--start-date`、`--end-date` 必填，按 `ann_date` 闭区间过滤 |
| R3 | 路径按 `YYYY-MM-DD/ts_code/文件名.pdf` 组织 |
| R4 | 文件名使用 `title`；清理不合法字符，防同名覆盖 |
| R5 | `--interval-seconds` 可指定请求结束到下一请求开始的最短间隔，重试、重定向同样遵守 |
| R6 | 每文件落盘、保存账本；取消、退出、重复命令后可靠续跑 |
| R7 | 数据库连接、创建归档目录及发起 HTTP 请求前，必须通过外部磁盘有效性检查 |
| R8 | 重复执行重新枚举所选日期，纳入新公告；成功文件经校验后跳过 |

第一版只提供单个下载命令，不扩展调度、页面、OCR、全文检索或交易能力。既有公告同步入口、字段合同、数据库表与 Lake 主链不变。

## 4. 使用方式

拟定命令，当前不可执行：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local python -m src.scripts.download_announcements \
  --start-date 2025-01-01 \
  --end-date 2026-09-30 \
  --interval-seconds 5 \
  --output-root /Volumes/datasource/announcements
```

环境文件复用现有 `GOLDENSHARE_ENV_FILE` 和 `DATABASE_URL`，不新增另一套数据库配置；终端只显示脱敏环境标识，不能打印连接串或密码。当前配置加载器可能回落 localhost，因此此工具必须确认存在显式 `DATABASE_URL`，不能依靠默认值偷偷连本地库。

相同日期与归档根重复执行就是续跑。间隔可在下次启动调整，不改变文件身份；本次实际参数记录在账本中。日期不同可共享同一归档账本，不能同时运行两个写同一归档根的进程。

## 5. 目录和命名

```text
/Volumes/datasource/announcements/
  2026-09-30/
    600000.SH/
      关于召开股东大会的公告.pdf
      董事会决议公告__<短哈希>.pdf
  .state/
    archive.lock
```

下载账本保存在本机 `~/Library/Application Support/Goldenshare/announcement-download/<归档身份>/downloads.sqlite`，归档身份由卷 UUID 和卷内相对目录生成，不增加 CLI 参数。PDF 与暂存文件在外盘，账本在本机，避免拔盘同时丢失恢复信息，也避免 SQLite 按绝对路径重开 journal 时误写同名挂载目录。

标题保留中文，统一 Unicode NFC，替换路径分隔符、控制字符及跨平台不安全字符，按 UTF-8 字节限制截断。完整原始标题保存在账本中。代码必须符合路径安全校验；不能由元数据构造 `..` 或越界路径。

同一日期、代码、URL 的多条记录复用一个下载文件，并保留全部行身份映射。URL 去首尾空白后保持原样，不擅自删除 query、改写协议或猜测同一文档。不同 URL 即使标题相同也分别归档；发生文件名冲突时追加下载身份短哈希，冲突仍存在就延长哈希。已有未知文件不能覆盖或自动删除。

## 6. 外部磁盘启动门禁

检查顺序：参数校验 → 只读识别外部卷 → 固定卷身份与目录句柄 → 写入探针和空间检查 → 本地账本及锁 → 数据库枚举 → HTTP 下载。

macOS 第一版使用系统现有 `diskutil` 的 plist 输出确认挂载点、卷 UUID 和外部物理介质；APFS 需要追溯底层 physical store，不能仅凭卷名判断外置。未知、无法核验、内部盘、未挂载或只读卷直接失败。检查前禁止 `mkdir -p /Volumes/datasource`。

目标可由 `--output-root` 指定，但必须在通过校验的外部卷内，且不得落入 DG 正式 Lake、staging 或退役 Lake 路径。不存在的 `announcements` 子目录只能在卷确认后创建。路径不得经符号链接逃逸。

建立固定外部卷目录句柄，后续本地文件操作使用相对句柄并拒绝符号链接，避免“先检查、再拔盘、再按绝对路径写”的竞态。运行中每批数据库读取、每个 HTTP 请求和文件提交前重新核验卷 UUID、设备和挂载状态；拔盘或设备变化立即停止，不能自动回落系统盘。

写探针仅创建、同步并移除本工具的随机临时文件，不接触用户已有文件。空间不足或文件系统不支持必要同步语义时失败。设计默认安全余量和单文件上限见 LLD；真实磁盘验收仍待执行，不能把目录存在当作已通过。

## 7. 下载与恢复设计

数据库每批最多 500 行，每批关闭只读事务，将记录与下载身份写入本地 SQLite 后才推进本地游标。枚举阶段不下载。完整枚举后进入逐文件下载，因此终端能显示确定的待处理总量。

每次命令创建新的元数据枚举轮次，从所选日期重新读起。上一次未完成轮次及其游标保留用于诊断，但不用旧高水位掩盖新公告；已入账的文件任务通过唯一下载身份复用。新轮次中途退出不会产生 PDF 重复下载，内存仍只保留一批。枚举不是数据库一致性快照，不能作为并发元数据更新的完整性证明。

文件流式写同目录 `.part`，校验后先记录待提交大小、SHA-256，再以同文件系统 `os.replace()` 原子提升，最后记录成功。恢复时必须处理“文件已提升、账本尚未成功”的窗口。SQLite 写失败应停止领取新文件，不能删除已经提交的 PDF。

第一版支持文件任务级续跑，不实现 HTTP Range 字节续传。未完整下载的 `.part` 下次从头下载该文件；大范围任务中已完成文件保留。复用成功文件前校验大小与 SHA-256，缺失或损坏才重新下载。

## 8. 控速和异常

默认单线程、固定间隔 5 秒；显式指定 `0` 可用于 debug，负数、NaN 和无穷值非法。所有实际 HTTP 请求，包括重试和每跳重定向，都通过同一个限速器。禁用自动重定向，避免它绕过间隔。

`429` 和带 `Retry-After` 的临时错误遵守服务器等待；未提供时指数退避。等待时间取请求间隔、退避和服务器要求的最大值，可取消，不使用忙等待。等待期限落本地账本，重启不能清空冷却。`403` 或识别到验证码/拦截页停止本次运行，保留状态和原因；不切换代理、伪装身份或绕过访问控制。

HTTP 200 不能直接证明 PDF 有效。验证 PDF 文件头、大小、响应截断和尾部基本结构；发现 HTML 错误页拒绝。此为传输和基础格式验收，不证明每页均能解析，第一版不安装完整 PDF 解析器。

## 9. 规模、进度与实施阶段

设唯一文件数为 N、平均每份传输用时为 D、请求间隔为 I、额外重试和重定向请求为 E。粗略耗时为 `N×D + max(N+E-1,0)×I + 额外退避`，必须以实际样本校准；没有样本不能承诺全量完成时间或容量。

5 秒间隔下，1,000 次请求仅等待约 83 分钟，10,000 次约 13.9 小时。进程常驻内存上限设计为一批 500 条元数据加一个 64 KiB 下载块，不保留整区间 PDF 或整批响应正文。数据库 `id` keyset 查询实际访问量必须在代表性范围做 EXPLAIN 验收，不能把 LIMIT 误当成扫描上限。

终端至少每 5 秒更新阶段、日期范围、枚举量或完成量/总量、当前公司与公告、成功/失败/跳过数量、冷却期限和最后更新时间。枚举未完成时总量未知；ETA 显示暂无法估算，待下载阶段再依据样本估计。

| 阶段 | 交付与验收 |
| --- | --- |
| M0 文档 | 本方案、LLD、参数审计和索引；本轮仅完成此阶段的编写与静态检查 |
| M1 实现 | 独立 CLI、只读枚举、外盘门禁、账本、控速与文件提交；用户允许开发后进行 |
| M2 隔离验收 | 本地模拟 HTTP、故障注入、磁盘竞态、重定向/重试间隔和续跑测试 |
| M3 最小真实验收 | 用户允许后，从 Prod 只读取最多 5 个真实 URL，指定外盘完成下载—中断—续跑—读回 |
| M4 范围执行 | 用户指定日期和间隔后执行；文档完成不自动授权全量下载或元数据维护 |

没有新增功能拍板阻塞。URL 与磁盘真实验证、查询计划和环境依赖是实施验收项；发现它们要求改变本方案时，先修原文并报告差异。

详细模块、参数、状态恢复和正反例验收见 [LLD](/Users/congming/github/goldenshare/docs/datasets/anns-d-pdf-download-low-level-design-v1.md)。
