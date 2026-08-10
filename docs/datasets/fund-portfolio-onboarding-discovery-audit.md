# 基金持仓（`fund_portfolio`）接入发现审计

状态：**B7-M0 发现审计、[B7 LLD](public-fund-b7-fund-portfolio-low-level-design-v1.md)、M1 编码与本地门禁、M2 隔离 PostgreSQL 验收、M3 生产 migration/HDD/TaskRun/五段对账/幂等复跑均已通过。尚未历史回补或创建 schedule；历史规模与配额预估必须另行授权。**
首次审计：2026-08-03；复审：2026-08-05、2026-08-08；M3 生产验收：2026-08-10
截图菜单：基金持仓
源文档：[公募基金持仓数据](../sources/tushare/公募基金/0121_公募基金持仓数据.md)

## 结论

`fund_portfolio` 是按季度报告期末披露的基金-证券持仓明细，不是每天更新的数据集。2026-08-08 以固定请求预算对 `19980331..20260630` 的 114 个候选季度末逐个执行 `period + limit=1` 存在性检查：只有 `19980331` 为空，从 `19980630` 到 `20260630` 的 113 个季度连续非空，且返回 `end_date` 始终等于请求 `period`。这关闭了此前只用样本基金起点推断历史季度的证据缺口，但没有用高成本全量分页冒充逐期精确行数。

`start_date/end_date` 不能作为报告期范围输入：对 O、E 样本传入 `20250101..20251231`，返回的是 `ann_date` 落在 2025 年内的数据，因而包含 `end_date=20241231`，但不含公告发生在 2026 年的 `end_date=20251231`。分页已确认可用：`period=20250630`、8 个显式字段、`limit=2000` 已连续取得 offset `0..660000` 的 662,000 行且仍为满页；随后以 `limit=8000` 只读定位到末段 `offset=1307500` 的 5,298 行，得到该时点全源结果为 **1,312,798** 行。未分页的 8,000 行只是单页，不是报告期总量。

因此，全量接入不受“源端不能分页”阻断，但当前主链不能直接承载：`DatasetSourceClient` 会把一个 unit 的所有页累积到 `rows_raw`，`IngestionExecutor` 随后才统一归一化、写入并 commit。B7 必须增加显式 opt-in 的页流式处理，做到每页读取、归一化和写入时释放 Python 行内存；但根据当前执行架构基线，**业务事务仍必须以逻辑 unit 为边界，不能把 offset page 变成提交边界**。此前文档中的“每页提交”是审计误判，本轮已纠正。

M0 新证据同时暴露出主路径成本冲突：生产 `fund_basic_current` 当前为 32,342 只基金；若继续使用 `(period, ts_code)` 主路径，113 个历史季度至少需要 3,654,646 次源请求。2025Q2 的全市场 `period` 基线只需 657 页；按同规模外推 113 期为 74,241 次，约为逐基金路径的 1/49.2。2026-08-08 用户已拍板不做 A/B 双遍，固定全市场 `period` 单遍分页、非服务中间态和整期原子发布；`period + ts_code` 只作定向修复。

## 源端事实与实测

| 项目 | 已核验事实 | 接入含义 |
| --- | --- | --- |
| 无参数 / 只有范围 | 均报“ts_code, ann_date, period 至少输入一个” | 不支持 snapshot 或纯 start/end range。 |
| 单基金历史 | `000001.OF` 6,317 行、98 个连续季度末（2002Q1..2026Q2）；`001753.OF` 43 个（2015Q4..2026Q2）；`015477.OF` 15 个（2022Q4..2026Q2）；`510300.SH` 返回 49 个季度末但总行数正好 8,000，必须按分页继续核验 | `end_date` 在样本中是季度末；无 period 的单基金历史可能触发页上限。 |
| `period` 点过滤 | `period=20250630`：`000001.OF` 187 行（公告日 20250721、20250830），`015477.OF` 274 行（20250721、20250831），`510300.SH` 340 行（20250721、20250830）；三者均只有 `end_date=20250630` | `period` 是报告期末的正确源端点过滤；同一报告期的所有公告版本都必须保存。 |
| 公告日点过滤 | `ann_date=20250721` 分别返回 10、13、15 行；与 `period=20250630` 合传结果相同 | `ann_date` 是披露批次过滤，不是报告期身份，也不能取代 period。 |
| `start_date/end_date` | 对 `000001.OF`、`015477.OF`、`510300.SH` 传 `20250101..20251231`，均返回 `end_date=20241231/20250331/20250630/20250930`，所有返回 `ann_date` 都在 2025 年内 | 实测按公告窗口过滤，与本地源文档“报告期开始/结束”文字不一致；不得把它暴露为报告期回补输入。 |
| 全市场季度分页 | `period=20250630`，offset `0..660000` 每页 2,000；以 `limit=8000` 定位到末段 `offset=1307500` 返回 5,298 行，合计 1,312,798 行 | 源端分页正常且持仓规模很大；按 2,000 行折算至少 657 页。 |
| 身份样本 | 单基金全历史 1,598 行和季度 8,000 行中 `(ts_code,ann_date,end_date,symbol)` 无重复 | 是候选幂等键，不替代跨期修订验证。 |
| 数据质量 | 样本 `stk_float_ratio=95,349,496.79`，与文档“占流通股本比例”不符 | 不能在服务层把它按百分比展示或缩放。 |
| 分页 | 2026-08-05 的 MCP/项目 connector 已验证多页；2026-08-08 当前 MCP 工具签名未暴露 `limit/offset`，项目 `TushareHttpClient` 的 114 次 `limit=1,offset=0` 请求均成功 | Definition 可使用 `offset_limit`；本轮不虚报 MCP 分页复验，也不重拉已有 131 万行证据。 |
| 代码批量 | `ts_code=015477.OF,000001.OF`、`period=20250630` 返回空集；两个代码单独请求均有数据 | 文档未定义代码列表语法，不能把逗号拼接当作源端批量能力。 |
| 公告日分桶 | 同一季度首个 8,000 行的 `ann_date` 均为 `20250831` | 不能因存在 `ann_date` 参数，就假定“一个公告日 = 有界 unit”。 |
| 默认字段与显式字段 | `000001.OF + 20250630` 默认与显式 8 字段均为 187 行，完整行多重集相等 | 生产请求仍必须显式请求全部 8 字段；默认等价只作源端对照。 |
| 历史报告期 | 114 个季度末候选中，`19980331` 为空；`19980630..20260630` 连续 113 期非空 | 历史清单按离散 `period` 管理，不构造日请求，也不使用 `start_date/end_date`。 |
| 生产对象池 | `fund_basic_current` 为 E 2,883 + O 29,459 = 32,342；代码、实体键均无重复，空代码 0 | 旧文档的 32,326 已过时；不得加 `status` 或市场裁剪。 |

已确认、后续 Definition 必须原样使用的 `source_fields`：

```text
ts_code, ann_date, end_date, symbol, mkv, amount, stk_mkv_ratio,
stk_float_ratio
```

`tushare-data` 的接口家族结论：这是公募基金季度披露的“基金—证券持仓事实”接口，与基金日净值、场内日行情和技术因子不是同一时间模型。

## B7-M0 请求、容量与代码证据

### 请求预算和结果

- 本轮先固定最多 120 次 Tushare 请求，实际调用 119 次：5 次 MCP 字段/多重集验证，114 次项目 HTTP client 季度存在性盘点；导入失败的两次本地脚本启动发生在发出源请求前，不计源调用。
- 没有重拉 2025Q2 的 1,312,798 行全市场基线，没有创建 TaskRun、schedule、probe、migration 或业务表写入。
- 生产只读查询只访问 `core_serving.fund_basic_current` 的聚合字段；总行数与 distinct `ts_code` 均为 32,342，E/O 均无空代码或重复实体。

### 请求量与耗时场景

以下为规划场景，不是永久 SLA；均未计网络延迟、重试、归一化和数据库写入时间。

| 主路径 | 单个报告期基础请求 | 113 期请求场景 | 200 次/分钟理论下界 | 500 次/分钟理论下界 |
| --- | ---: | ---: | ---: | ---: |
| 逐基金 `(period, ts_code)` | 32,342，加少数多页 | 至少 3,654,646 | 304.6 小时 / 12.7 天 | 121.8 小时 / 5.1 天 |
| 全市场 `period` 单遍 | 以 2025Q2 为 657 页 | 以各期均按 2025Q2 规模计为 74,241 | 6.2 小时 | 2.5 小时 |

第二行只是“113 期都等同 2025Q2”的统一规模场景；早期季度通常更小，但本轮没有为了取得精确逐期行数继续消耗额度。生产凭据实际属于 200 还是 500 次/分钟档位仍须在隔离/生产门禁中预检，代码不得默认按较高档位执行。

### HDD、WAL 与行数场景

- 生产 `gs_raw_cold_hdd` 位于 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`；`/data/disk` 为 `/dev/vdb` ext4，当前总 422,549,692,416 bytes、可用 342,549,856,256 bytes，tablespace 已用约 54 GiB。
- 2025Q2 的 1,312,798 行重复套到 113 期得到 148,346,174 行场景；它不是实测历史总行数，更不是上限。
- 当前 187 行 MCP JSON 样本平均约 181.3 bytes/行，只能说明传输文本量。若最终“表 + 全部索引”按 400/600/800 bytes/行做规划带宽，历史场景约为 55.3/82.9/110.5 GiB；真实值必须由 M2 的 PostgreSQL 大样本得到，LLD 不得把这些带宽写成实测值。
- 集群配置为 `max_wal_size=1 GiB`、`checkpoint_timeout=300s`、`full_page_writes=on`、`wal_compression=off`、`wal_level=replica`；WAL 累计统计不能分摊到 B7。应用数据库角色无权读取 `pg_ls_waldir/data_directory`，M2/M3 必须使用对应环境的主机只读水位和单事务 LSN 差量。

### M0 时点的代码影响面（已由 M1 实现取代）

- M0 时点代码中尚无 `fund_portfolio` Definition、request builder、ORM、DAO、migration、Ops item 或测试；当时 Alembic head 为 `20260807_000130`。
- `src/foundation/ingestion/source_client.py` 的 `SourceFetchResult.rows_raw` 是完整 list，offset 循环使用 `rows_raw.extend(rows)`；不能直接执行 131 万行全市场 unit。
- `src/foundation/ingestion/executor.py` 只接受完整 fetch result，并在 normalizer/writer 后以 unit 为边界 commit/rollback。分页流式化会影响 source client、executor、normalizer/writer 调用方式、progress/TaskRun diagnostics、取消与重试语义。
- 当前通用 `DatasetUnitPlanner._resolve_universe_values` 只直接支持 `no_pool`；B7 若使用对象池必须增加从 `fund_basic_current` 读取稳定全量代码的声明式 source/custom builder，禁止把基金代码池写成 dataset-key 分支或 ETF 池复用。
- CodeGraph 影响面确认 `DatasetSourceClient` 直接影响 `IngestionExecutor` 的串行/并发 fetch 主链；`IngestionExecutor` 再影响 unit commit、progress、pagination diagnostics 和错误回滚。B7 流式能力必须显式 opt-in，现有数据集默认 list-fetch 路径不得改变。

上述条目是 M0 编码前快照，不是当前代码现状。M1 已用 Definition 显式 opt-in 实现 staged stream，并新增 final/stage 显式列 ORM、专用 DAO、migration、Ops/UI 契约和回归测试；实现证据与当前文件清单以 B7 LLD 为准。

## 建议的接入轮廓（非 LLD）

| 维度 | 当前建议 |
| --- | --- |
| 时间输入 | 以报告期 `period` 为一等输入；不能误用“每天”或泛化 `start_date/end_date`。 |
| 完整源范围 | 保存 Tushare 返回的全部 E/O 源事实；`fund_basic_current` 当前 32,342 只只作已验收上游背景，不参与全市场主请求过滤，也不限制定向补录代码。 |
| 主执行路径 | **已拍板**：全市场 `period` 单遍分页写入非服务中间态，完成 short page 、字段/报告期、身份冲突和全链路数量检查后整期原子发布；`period + ts_code` 只作定向修复。不做 A/B 双遍。 |
| 分页与事务 | 两种路径都固定 `limit=2000`、offset 递增、short page 才结束、无任意页数上限。每页可读取、归一化、写入并释放内存，但只有逻辑 unit 完成后才能形成可见业务提交；禁止把 offset page 直接计为完整业务事实。 |
| 重试 / 观测 | 记录逻辑 unit、page/offset、累计 fetched/normalized/staged、最终 committed 与 reject；未到 short page 的数据不得显示成已提交。重试必须幂等，且不能把前几页冒充完整 scope。 |
| 任务切片 | 一个 `period` 是一个发布 scope；LLD 固定 range 只展开季度末、单 TaskRun 最多四期，并由 staged publisher 的 PostgreSQL session advisory lock 串行化 B7 execution。 |
| freshness / audit | 季度披露且有公告滞后，先用 `not_applicable`；是否建立季度披露完整性必须有基金池、报告期和发布窗口规则。 |
| 依赖 | B2 已完成是批次进入前置，但 B7 主请求不读取 `fund_basic` 对象池；不得借用 ETF 活跃池，也不得因对象池、代码后缀或市场名称排除 Tushare 已返回的记录。 |
| 自动化 | 支持普通定时自动任务；本期不接 probe。 |
| 存储 | 所有 8 源字段保存；只保存单事实表，不增加 observation 版本表；业务表、全部叶分区和索引固定 HDD。PostgreSQL 集群共享 WAL 保持当前 SSD，不为本数据集迁移 `pg_wal`。 |

## 完整请求与对账契约（非 LLD）

所有生产主请求都必须显式请求全部 8 个 `source_fields`，只使用 `period` 作为报告期语义，并由 connector 追加 `limit=2000/offset`。禁止把 `ann_date`、`start_date/end_date` 或 `symbol` 放入全量主请求；它们会缩小完整报告期。禁止逗号拼接代码。

分页从 offset 0 开始；每页必须校验 `end_date` 等于请求 `period`。定向补录还必须校验 `ts_code` 等于请求基金。每页立即归一化、写入非服务 stage 并释放内存；只有收到 short page、完成完整性检查并形成 unit 级业务提交后才算成功。若上页恰好 2,000 行，必须继续请求下一页，下一页为空才是正常结束。

源接口没有 snapshot ID，且已拍板不做 A/B 双遍，因此不宣称能证明长分页期间源端绝对静止。单遍必须把全部页写入当次 `period` 的非服务中间态，逐页校验八字段完整性和 `end_date=period`，且只有收到 short page、全程无请求/归一化失败、无同一完整身份内容冲突，并完成源端、归一化、中间态和拒绝数量对账后，才能原子发布该报告期的新事实。既有不可变事实不删除；源 scope 回退或内容冲突时整期失败。任一分页失败或中断都不发布。

历史回补不能根据 `start_date/end_date` 生成区间。离散清单已经固定为 `19980630..20260630` 连续 113 个季度；后续新增季度按季度末追加。该清单不授权历史回补，也不代表每期精确行数已经枚举。

## LLD 前已定口径

1. **完整源范围已定**：保存 Tushare 返回的全部记录；不允许 ETF 池、仅 O、仅 E、代码后缀白名单或 `status` 过滤。
2. **主执行路径已定**：全市场 `period` 单遍分页、非服务中间态、整期原子发布，不做 A/B 双遍；以 2025Q2 规模外推 113 期为 74,241 次请求，约为逐基金路径的 1/49.2。这是容量场景，不是逐期精确请求量。
3. **版本存储已定**：候选事实身份固定为 `(ts_code,ann_date,end_date,symbol)`，不同 `ann_date` 必须并存。只建单事实表，不建 observation 版本表：同一完整身份且 8 个源字段完全相同时幂等去重；同一完整身份但内容不同时整个 `period` fail-closed，不发布且进入人工核查。
4. **事务语义已纠正**：分页只作流式内存边界，业务 commit 仍以逻辑 unit/原子发布 scope 为边界；未完成页不得成为 serving 完整事实。
5. `stk_float_ratio` 首版只按源值保真存储，不做百分比缩放或业务解释；这不阻塞接入，后续有权威单位说明再补展示语义。

## 已确认的事实身份边界与待固化项（非 LLD）

1. 持仓源事实的候选逻辑身份为 `(ts_code, ann_date, end_date, symbol)`：同一报告期同一证券在不同公告日披露，必须视为不同披露事实，不能按 `ts_code + end_date + symbol` 覆盖。
2. 全部 8 个源字段都必须参与内容散列。同一候选身份且内容完全相同是幂等重复，只保留一条；同一候选身份内容不同是冲突，整期 fail-closed 并人工核查，不保留观察版本。这不改变“报告期 + 公告日”是业务事实的边界。
3. 同一报告期的 `ann_date` 多版本是完整源事实：`period=20250630` 样本中早期公告仅 10/13/15 行，后续公告补足到 187/274/340 行；任何仅按早期公告日增量的设计都会漏源记录。
4. 当前实现的 `DatasetSourceClient` 先将所有页累积为 `rows_raw`，`IngestionExecutor` 才归一化并在外层逻辑 unit 末尾 commit。流式分页必须改为“页级读取/归一化/写入、unit 级提交”；这会影响共享 source client、executor、事务 lint、进度/TaskRun 对账和相关测试，必须显式 opt-in，不能改变其他数据集默认路径，也不能只按 `fund_portfolio` key 写分支。
5. LLD 已取消逐基金代码切片主路径：全市场一个 `period` 是一个 unit；`period + ts_code` 只做已有 period 的单基金补录。B7 staged publisher 使用由 Definition write path 选择的 execution 级 advisory lock，避免多个 B7 TaskRun 同时消耗配额或污染暂存态，不在 source client/executor 中按 dataset key 特判。

## M2/M3 验收补充证据

- M2 在隔离 PostgreSQL 验证 32 个 HDD 叶分区、UNLOGGED stage、1,312,798 行合成容量、幂等、中断/最终事务回滚与 advisory lock；`period=19980630` 真实最小 scope 为 42 行、0 reject。
- M3 生产 Alembic head 到达 `20260810_000131`；final parent、32 leaves、66 个 final indexes、UNLOGGED stage 与 2 个 stage indexes 全部位于 `gs_raw_cold_hdd`，非 HDD 物理对象数为 0。
- 生产 TaskRun `#7813` 为 `42 fetched / 42 saved / 0 deduplicated / 0 rejected`，首次 `42 inserted`；`#7814` 幂等复跑 `0 inserted / 42 matched`。两次均无 TaskRun issue，源端与目标端规范集合摘要一致，目标 content hash 重算不一致为 0，stage 最终为 0。
- M3 仅用 3 次单页 Tushare 请求完成生产 connector 基线、首跑与幂等复跑，未扫描历史。该单页 scope 不能消除长分页 offset 漂移风险；M4a/M4b 仍需独立检查请求预算、HDD 容量和 SSD/WAL 停止阈值。
