# 股票日线九转 M3 serving 发布门禁 v1

> 状态：M3-A/M3-B 已完成。M3-C 的生产日线接口、权限、真实数据对齐和 1600×1200 Loaded 视觉已完成代表性验收；正式 P95 仍缺足量登录态 HTTP 样本，生产页缩放到 45/180 根边界的浏览器截图仍待补齐，因此完整 M3-C 尚未最终收口。M3-C-Minute 的 30/60/90/120 分钟接口、性能、内存、浏览器和视觉行为验收已完成，1/5/15 分钟禁用口径已验证为零九转请求；2026-08-15 新冻结的分钟无价格八列物理合同尚未实施。三个股票九转 sensor 的正式实例状态均为 `RUNNING`、最近 tick 均 `SKIPPED`；定义默认 `STOPPED` 不能替代当前实例状态，详细快照见总方案第 3.3 节。

> 总方案：[股票与主要指数详情页九转接入总方案 v1](./detail-page-nine-turn-integration-implementation-design-v1.md)

> LLD：[股票与主要指数详情页九转接入低层设计 v1](./detail-page-nine-turn-integration-low-level-design-v1.md)

## 1. 目标和退出边界

M3-A 纠正“文件齐全即可发布”的错误前提；M3-B 把发布改成可阻断、可审查、可中断、可续跑的正式链路。

本门禁通过本身不授权以下动作；2026-08-13 的 Gold 修复和日线 serving 分批发布均在用户另行批准后执行：

1. 修改正式 Gold 文件。
2. 向生产 `core_serving.equity_qfq_nineturn_daily` 写入数据。
3. 运行 materialize、backfill、runless event 或历史 publisher。
4. 启用任一股票九转 sensor。

## 2. M3-A 事实基线

| 项目 | 2026-08-13 只读结果 |
|---|---:|
| Alembic head | `20260813_000135` |
| 生产目标表 | 已存在，0 行 |
| Gold 九转分区 | 3,066 |
| 覆盖 | 2014-01-02 ～ 2026-08-12 |
| Gold 九转键数 | 11,638,636 |
| QFQ 行情键数 | 11,638,636 |
| 缺失/多余键 | 0 / 0 |
| `close_qfq` 漂移 | 45,442 行、18 只股票、3,065 个交易日 |
| 漂移股票公式重算 | 45,483 行比较，计数/信号差异 0 |
| Gold 修复后全历史对账 | 11,638,636 行；键、价格、计数、信号差异均为 0 |
| serving 最终检查点 | 3,066 / 3,066 个交易日；剩余 0 |
| serving 最终生产对账 | 11,638,636 行；日期缺失/额外/逐日行数不符均为 0 |

结论（M3-A 当时）：页面 marker 算法结果没有发现差异，但九转 Gold 保存的价格已经不是当时 QFQ 事实。发布表包含 `close_qfq`，因此先执行 scoped rebuild，再发布。后续 M3-B 已完成 45,442 行漂移修复、11,638,636 行键/价格/计数/信号零差异对账和全历史 serving 发布；该问题不再是当前未修复项，日线逐键价格一致性门禁继续保留。

## 3. 不可变发布门禁

1. Gold check 同时验证文件、分区、键、值域、源键覆盖和源收盘价一致性。
2. serving loader 再次运行同一门禁，不能靠跳过 Dagster check 绕过。
3. 正式 Lake 只允许 `raw/silver/gold`；候选、恢复副本和 checkpoint 只能进入 `/Volumes/datasource/data_lake_staging`。
4. 历史发布先 `plan`，计划绑定 Gold/QFQ 文件路径、size、mtime、行数和 fingerprint。
5. Gold scoped rebuild 与 serving 发布都要求 `sample` 只允许 1～3 个计划内分区；单个逻辑 `batch` 最多 20 个分区。Gold 修复一次已审批运行最多 200 个 batch；serving 因真实内存事件收紧为单进程最多 10 个 batch，即最多 200 个交易日，必须退出进程释放内存后再续跑。
6. 每个交易日独立事务；read-back 通过后才原子记录 checkpoint。
7. 续跑前先对计划冻结的全部 Gold/QFQ 文件做相对路径、size、mtime 元数据核对，再使用 PostgreSQL server cursor 流式回验 checkpoint 已完成日期的精确业务内容 hash；任一不一致立即停止。仅本次待发布分区重新执行完整 Gold/QFQ 内容门禁，禁止每次恢复都深扫全历史。
8. serving check 为 blocking，比较行数、键和业务内容 hash。
9. 日常 serving job 独立于 Gold job；下游 sensor 定义默认 `STOPPED`。正式实例持久化状态是独立运行事实，当前值见总方案第 3.3 节。
10. 不使用 Tushare、Mock、客户端重算或空表作为 fallback。
11. serving 历史发布专用 DuckDB 固定 `memory_limit=128MB`、`threads=1`、`preserve_insertion_order=false`；不得沿用通用 16GB 上限。
12. 每个 20 日 batch 复用一组 DuckDB、PostgreSQL 写连接和只读连接；每个交易日仍显式 commit、read-back、结束只读事务和写 checkpoint。
13. `plan` 的完整 3,066 分区明细只写报告文件；CLI 只打印固定大小摘要。发布进度每个逻辑 batch 最多打印一条，不逐日打印；最终结果不得携带完整 selected/published/resumed 日期数组。

## 4. 代码落点

| 能力 | 文件/定义 |
|---|---|
| Gold 源值门禁 | `qfq_nineturn_integrity.py` / `source_value_consistency` |
| scoped rebuild plan/sample/batch/resume | `qfq_nineturn_history.py` |
| 历史 plan/sample/batch/resume | `stock_daily_qfq_nineturn_serving_history.py` |
| 显式 CLI apply 门禁 | `stock_daily_qfq_nineturn_serving_history_cli.py` |
| serving blocking check | `prod_core_stock_daily_qfq_nineturn_partition_check` |
| 日常 serving job | `prod_core_stock_daily_qfq_nineturn_sync_job` |
| 定义默认停止的 sensor | `prod_core_stock_daily_qfq_nineturn_sync_job_sensor`；当前实例状态见总方案第 3.3 节 |

## 5. 配置审计

本轮不新增环境变量。正式根继续使用既有常量：

| 配置 | 值/来源 | 消费者 | 生效方式 |
|---|---|---|---|
| Lake root | `/Volumes/datasource/data_lake` / `DEFAULT_LAKE_ROOT` | plan、Gold loader、scoped rebuild | CLI/运行时 |
| Staging root | `/Volumes/datasource/data_lake_staging` / `DEFAULT_LAKE_STAGING_ROOT` | rebuild 候选、备份、checkpoint | CLI/运行时；正式根不可改 |
| Prod write env | `PROD_POSTGRES_WRITE_*` | serving asset、history publisher、serving check | 运行时 |
| serving DuckDB 内存 | `128MB` / 发布器代码常量 | serving plan、resume、publish | 每次连接建立后强制设置 |
| serving DuckDB 线程 | `1` / 发布器代码常量 | serving plan、resume、publish | 每次连接建立后强制设置 |
| serving 单进程批次数 | 最多 `10` | history publisher | CLI 参数校验；每批最多 20 日 |

CLI 虽保留 fixture 参数用于隔离测试，但正式 Lake 模式会强制固定 staging 根，不能用参数改到正式 Lake 内部。

## 6. 性能与事务预算

1. 历史规模为 3,066 个分区、11,638,636 行，约 13,472 个 1,000 行插入页。
2. 单日最多约 5,539 行；事务边界固定为一个交易日。
3. Gold scoped plan 只扫描目标资产族；本轮日线修复不再顺带扫描四个分钟资产。
4. 每个逻辑 batch 最多 20 个交易日；Gold 修复单次最多 200 个 batch，serving 单进程最多 10 个 batch。两者都逐日 checkpoint，失败不撤销已经回验通过的早期日期。
5. Gold 每个交易日使用独立候选、完整 blocking check 语义、同文件系统 `os.replace()` 和保留于 staging 的恢复副本；执行前按所选分区计算磁盘预算。
6. serving 每个交易日使用独立 PostgreSQL 事务；checkpoint 每成功一个交易日原子写一次。
7. 计划阶段每个分区只执行 SQL 完整性聚合并取得 `checked_row_count`，不再把整分区记录 `fetchall()` 到 Python；每 20 日关闭并重建 DuckDB 连接，释放 allocator 高水位。
8. 恢复阶段不再重新生成覆盖 3,066 日、6,132 个文件的深度计划；只做 6,132 个文件的固定元数据核对、已完成 Prod 行的 server-cursor 流式 hash，以及最多 200 个待发布日的深度校验和写入。
9. 修正前证据：128MB/单线程全历史计划峰值 RSS 约 316MiB；913 个已完成日的流式恢复回验峰值约 156MiB；随后 200 日发布进程峰值约 340MiB，立即再启恢复进程时峰值约 412MiB。根因是同一进程串行执行全历史深度重计划、已完成 Prod 回验和发布，叠加 DuckDB allocator 高水位；PostgreSQL 单日约 2,000～5,539 行写入不是主要放大点。
10. 修正后正式只读验收：3,066 日、6,132 文件、11,638,636 行的全历史 plan 用时 17.60 秒，峰值 RSS 248,348,672 bytes（约 237MiB），指纹与原计划一致；1,113 个 checkpoint 日期、2,770,508 行 Prod 精确 hash 回验全部通过，用时 187.39 秒，峰值 RSS 163,987,456 bytes（约 156MiB）。两项分进程执行，均未写 Lake 或 Prod。
11. CLI 曾打印 3,066 个完整计划对象、全部日期数组和逐日进度，产生 325KB 以上单次输出并放大 Codex 渲染内存；本轮正式 plan 摘要仅 526 bytes，恢复验收摘要 148 bytes，发布过程改为逐 batch 进度。该问题与数据写入正确性分开处理。
12. 修正后从 1,113 日恢复到 3,066 日，共使用 10 个独立短进程（九次 200 日、最后一次 153 日）；各进程最大 RSS 为 209～249MiB，最高 260,833,280 bytes，未触发 512MiB 观察阈值或 1GiB 中止阈值。最后进程最大 RSS 为 241,074,176 bytes，检查点剩余为 0。
13. 恢复回验耗时随已完成分区增长，最后进程总耗时约 932 秒，其中写入阶段约 215 秒。它是 server-cursor 精确内容 hash 的线性耗时问题，不是常驻内存增长；后续若优化恢复性能，必须保留“源身份 + 已完成生产内容”双重 fail-closed 语义。
14. 同期只读观察到长期运行的 Dagster Definitions gRPC 进程 RSS 约 6.6～7.4GiB；调用 Definitions/sensor 只读查询后为约 7.4GiB，随后 30 秒采样保持不变。该进程不是历史 publisher，不能把其内存归因于 PostgreSQL 日线写入；应另立 Dagster Definitions 常驻内存审计，本轮不混改、不停止该进程。

## 7. M3-B 验收矩阵

1. close 相同通过，close 漂移阻断，failure sample 可定位代码和数值。
2. Gold key 缺失、额外 key、重复 key、值域错误继续阻断。
3. 正式 Lake 内 staging 路径被拒绝；fixture Lake 与 staging 也不能相同；checkpoint 只能位于已审核 staging 根下。
4. 计划文件被改、源文件 size/mtime 变化、fingerprint 错配均在写 Prod 前停止。
5. Gold 与 serving 的 batch 上限 20；Gold 单次 batch 数上限 200，serving 单进程 batch 数上限 10，sample 上限 3；计划外日期拒绝。
6. Gold 提升或 serving 每日事务 read-back 漂移失败时，checkpoint 不记录失败日期；Gold 当前分区恢复原文件。
7. 第二次运行对全部冻结源做元数据身份核对，以流式游标验证已完成日期的目标 hash，并只对待发布日期重跑源内容门禁；发布函数不得再次调用全历史 `plan`。
8. serving check 为 blocking，catalog 登记一致。
9. job 只选择 serving asset/check；sensor 同分区触发且定义默认 `STOPPED`，实例当前状态另见总方案第 3.3 节。
10. 既有日线/分钟九转公式、页面 DTO、共享 primitive 和 API 回归不漂移。

2026-08-13 本轮内存与输出修正后的定向代码验收为 21 项通过；九转相关完整回归为 96 项通过、另有 14 个子测试通过，Ruff 与 `git diff --check` 通过。测试明确证明 plan 不再调用行装载器、publish 不再重建深度计划、CLI 摘要不含完整分区数组、进度仅按 batch 发出。正式只读 plan、checkpoint 回验和全历史生产逐日行数对账均已通过。`dg list defs` 已发现 serving asset、blocking check、独立 job 和 sensor；当时两个相关 sensor 被记录为 `STOPPED`，这是历史验收快照。2026-08-15 重新审计时，股票日线 Gold、股票分钟 Gold 和股票日线 serving 三个 sensor 均为实例 `RUNNING`，最近 tick 均 `SKIPPED` 且没有发起 run。M3-B 历史发布可以收口，但自然日常链路仍未完成，不能把股票九转整体标记为 production-ready。

## 8. M3-C 生产日线验收记录

2026-08-13 只读验收只覆盖生产日线，不生成分钟数据、不启用 sensor、不执行部署或生产写入。

### 8.1 生产装配与 HTTP

1. 生产远端为 `dev-interface@34421ef7`，与当时本地 `origin/dev-interface` 一致；Web、Ops Worker、Ops Scheduler 均为 `active`。
2. Web 入口为 `python -m src.app.web.run`，`/api/health` 与 `/api/v1/health` 均返回生产环境 `ok`。
3. 未登录直接请求日线九转接口返回 HTTP 401，证明路由存在且鉴权生效，不是 404。
4. 登录态页面真实请求：`600683.SH` 返回 HTTP 200、143.07ms；另一个生产样本 `688300.SH` 返回 HTTP 200、211.78ms。两次均低于 1.5s 目标，但样本数不足，不能据此宣称正式 P95 已通过。
5. 股票详情深链接 `https://wealthworld.com.cn/wealth/market/stock/600683.SH` 的外部只读探测返回 HTTP 200、TTFB 153.70ms。验收早期出现过一次 502，但后续公网探测和生产 Web 日志均无法复现，不登记为已确认缺陷。

### 8.2 生产数据样本

对 `600683.SH`、`endDate=2026-08-12`、`limit=300` 做有界只读审计：

| 项目 | 结果 |
|---|---:|
| serving 行数 / 匹配行数 / 缺失行数 | 300 / 300 / 0 |
| 实际覆盖 | 2025-05-22 ～ 2026-08-12 |
| 1～9 可展示 marker | 259 |
| 10+ 不应绘制的行 | 37 |
| 非 formulaVersion=1 | 0 |

最新八个交易日依次为上序 1～8；2026-07-16 为下序 9。生产页面右端实际绘制结果与该顺序一致。该样本同时证明 10+ 负向数据真实存在；DTO/前端回归已锁定 10+ 不生成 marker，生产截图未出现持续重复 9。

### 8.3 1600×1200 浏览器验收

1. 生产页实际绘出上下序数字和带描边完成态 9；marker 与对应 K 线贴附，没有扩大价格轴。
2. K 线、MA、MACD、成交量、KDJ、右栏、坐标轴和工具栏继续显示，无新增换行、裁剪、横向溢出或图表位移。
3. 日线默认约 120 根；右下角放大、缩小图标和可访问名称均存在。
4. Chrome 验收连接在连续点击缩放按钮时超时，未稳定取得 45 根放大上限和 180 根缩小上限的生产截图。共享组件自动化测试已证明 15 根步长、45/180 根禁用边界、不重建图表且不发请求，但这不能替代尚缺的生产浏览器边界截图。

### 8.4 自动化门禁

1. Web API、Reader、生产 serving 定义与同步：45 项通过。
2. 九转 registry、adapter、局部状态、shared primitive、股票详情和共享缩放：51 项通过。
3. Wealth `typecheck` 和生产构建通过；构建仅保留既有大 chunk 警告。
4. Wealth 全量测试为 189/192：3 项失败均在 `market-overview`，分别是两个本地 DEV 调试文案断言和一个榜单超时，与九转 API、图层或股票详情无调用关系。本专项不越界修改。

### 8.5 退出判断

生产日线的功能、权限、数据映射和 Loaded 视觉主体门禁已通过。M3-C 最终收口仍需：

1. 取得至少 10 次同口径登录态生产 HTTP 样本并计算 P95；目标不高于 1.5s，硬门禁 5s。
2. 在稳定浏览器连接下保存 45 根、180 根两个边界状态截图，确认对应按钮置灰且页面无漂移。
3. 完成一次自然日常更新链路验收；当前三个股票 sensor 虽为实例 `RUNNING`，但最近 tick 均被门禁跳过。本文不授权任何启停动作，后续处置须单独审批。

## 9. M3-C-Minute 本地分钟验收记录

2026-08-14 在用户确认四个股票分钟九转序列重建完成后，只读验收正式 Lake，并通过本地 Web 完成真实接口和浏览器验收。本轮没有 materialize、backfill、sensor、runless event、Lake 写入或生产写入。

### 9.1 Definitions、checks 与物理覆盖

1. Definitions 正确发现 `gold_stk_mins_qfq_nineturn_30m/60m/90m/120m` 四个资产及四个 matching blocking integrity checks。
2. 四个最新 `2026-08-13` 分区的 check 均为 `SUCCEEDED`，且 check target storage id 与各自最新 materialization storage id 相同：30/60/90/120 分钟依次为 `7150841/7153928/7157015/7160102`。
3. 四资产均有 3,067 个交易日分区，覆盖 2014-01-02 至 2026-08-13。
4. 最新分区 30/60/90/120 分钟行数依次为 44,320/22,160/16,620/11,080，代码数均为 5,540；重复时间键、分区日期错配和非法值均为 0。
5. 10+ 是正式数据常态，不得重复绘制 9。最新分区四周期的 10+ 行数依次为 1,418/1,259/989/879；Reader 和页面 DTO 只投影 1～9 marker。
6. 全仓日期审计中唯一缺失项是日线 `gold_stock_daily_qfq_nineturn` 的 2026-08-13 分区，不属于 M3-C-Minute，不阻断四个已通过最新 check 的分钟资产。

### 9.2 Reader 内存根因与修正

真实 HTTP 压测发现旧 Reader 每个请求创建一套 in-memory DuckDB，并对所选全市场日分区扫描全部股票行做合同校验。默认 500 根、40 次请求后 Web RSS 增长约 117MiB，第二批 40 次仍增长约 92MiB，属于持续高水位问题，不能带病验收。

根因修正遵守以下边界：

1. 全市场完整性继续由与当前 materialization 绑定的 blocking check 保证；Web Reader 仍验证正式路径、schema、分区和请求股票的行级合同，但不为单股票请求重复扫描其它股票。
2. 本地 composition root 按 Lake root 复用一个受锁 DuckDB 连接；固定 `memory_limit=256MB`、`threads=1`、`preserve_insertion_order=false`，不在每个 HTTP 请求重建连接。
3. Reader 提供幂等 `close()`；连接关闭后可按需重建。无关股票的坏行不会阻断当前股票，但当前股票的坏行、重复键或分区错配仍 fail closed。

修正后相同 Web 进程第一批 40 次请求由 222.56MiB 增至 352.48MiB，用于建立 DuckDB 高水位；第二批 40 次由 352.48MiB 增至 365.27MiB，仅增加 12.78MiB，低于 32MiB 目标和 64MiB 硬停止线。

### 9.3 真实 API、对齐与性能

1. 对 `000002.SZ`、`600683.SH`、`688300.SH` 的四周期各取 500 根：K 线、技术指标和九转时间键均逐根匹配，九转 source/matched/missing 为 500/500/0，marker 时间键全部属于 K 线集合，最大序号为 9。
2. 四周期两页 cursor 均稳定升序、无 marker 重叠；cursor 跨代码或跨周期复用返回 HTTP 400 `NT_REQUEST_INVALID`。
3. 1/5/15 分钟、未知或重复参数、非法代码和超限 limit 均返回 HTTP 400 `NT_REQUEST_INVALID`；生产或本地能力未就绪时不挂分钟路由。
4. 四周期各 10 次真实 500 根 HTTP 请求的 P95 为 362.24/399.30/499.98/487.62ms，均低于 1.5s 目标；4 workers、16 次并发请求最大 1,059.81ms，全部返回 200。
5. K 线和技术指标继续读取 `gold/quote/stk_mins_qfq`，九转只读取 `gold/indicator/stk_mins_qfq_nineturn`，未读取 Silver、旧 Lake 或 staging。

### 9.4 前端与 1600×1200 浏览器验收

1. `000002.SZ` 的 30/60/90/120 分钟均同时发起 K 线、技术指标和同频九转请求，三个接口均返回 200；K 线高低点外实际绘出 1～9 marker。
2. 1/5/15 分钟只请求 K 线和技术指标，九转请求数为 0，并显示“当前周期不提供九转序列”。
3. 切回已加载的 30 分钟没有新增 stock-detail 请求；点击放大后九转 marker、K 线、MACD、成交量、KDJ 和共享时间轴继续显示，九转图层没有重置或触发新请求。
4. 30 分钟、120 分钟及 30 分钟放大状态均以 1600×1200 实际页面验收；无新增换行、裁剪、重叠、横向溢出或右栏漂移，浏览器控制台无 warn/error。
5. 后端相关回归 39 项通过；九转前端定向回归 34 项通过；Wealth 全量 225 项通过；`typecheck` 和生产构建通过，仅保留既有大 chunk 提示。

### 9.5 退出判断

M3-C-Minute 的页面/API/性能行为验收已完成，但 2026-08-15 新冻结的无价格八列物理合同使其状态调整为“行为验收已通过、物理合同迁移待完成”。它不等于完整 M3-C 完成，也不授权启停 sensor；生产日线 P95、45/180 根边界截图和自然日常链路仍按 8.5 保持待验收。指数 M4-B 后端、正式历史和 serving 已在后续阶段完成，指数页面接入仍属于 M5。

## 10. 后续执行顺序

1. 已生成并审核 18 只股票 scoped rebuild 计划。
2. 已完成 3 个 Gold 样本、3,065 个修复分区及全历史 source-value/公式对账。
3. 已生成 serving history 计划并完成首、中、尾 3 天样本发布。
4. 已在代码修正和只读内存门禁通过后，以单进程最多 200 日的短进程从 1,113 日恢复到 3,066 日；最终 checkpoint、冻结计划和生产表逐日行数一致，剩余 0。该阶段结束时两个相关 sensor 保持 STOPPED；2026-08-15 的当前实例状态已变化，见总方案第 3.3 节。
5. M3-C 生产日线接口、权限、数据对齐和 Loaded 视觉主体门禁已通过；补齐登录态 P95 与缩放边界截图后收口日线切片。
6. M3-C-Minute 行为验收已完成、无价格八列物理合同迁移待完成；完整 M3-C 还剩生产日线 P95、生产 45/180 根边界截图和自然日常链路。三个股票 sensor 当前已是实例 `RUNNING` 但被门禁跳过；任何后续停止、恢复或运行口径调整仍需单独审批。

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-08-13 | 登记正式数据漂移事实，冻结 Gold 修复与 serving 历史发布门禁、代码落点、性能预算和后续执行顺序 | Codex |
| v1.1 | 2026-08-13 | 登记 Gold 修复完成、serving 893 日检查点、内存事件和 256MB/单线程/10批次短进程门禁 | Codex |
| v1.2 | 2026-08-13 | 同步 serving 1,113 日检查点；修复计划取全量行、恢复全历史深扫和超大 CLI 输出三处放大点，内存上限收紧到 128MB；正式只读验收通过，生产恢复仍待用户确认 | Codex |
| v1.3 | 2026-08-13 | 完成余下 1,953 个交易日的十进程有界发布；最终 3,066 日、11,638,636 行逐日对账通过，峰值 RSS 约 249MiB；M3-B 收口，M3-C 与自然日常链路仍待验收 | Codex |
| v1.4 | 2026-08-13 | 登记 M3-C 生产日线验收：登录态 API 200、真实 300 行样本无缺失、1600×1200 Loaded 视觉通过；正式 P95、生产缩放边界截图与分钟验收仍待完成 | Codex |
| v1.5 | 2026-08-14 | M3-C-Minute 收口：四分钟资产/check/物理覆盖、逐键对齐、严格接口、P95、两批 40 请求内存门禁及 1600×1200 浏览器验收通过；1/5/15 分钟九转零请求 | Codex |
| v1.6 | 2026-08-15 | 文档漂移收口：把 M3-A 价格漂移明确标记为已由 M3-B 修复；同步分钟无价格八列合同迁移待办，并登记三个股票 sensor 实例实际 RUNNING/最近 tick 均 SKIPPED，清除“当前两个 sensor 仍 STOPPED”的错误表述 | Codex |
