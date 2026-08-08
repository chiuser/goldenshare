# 基金分红（`fund_div`）接入发现审计

状态：**B4-FD-M0/M1/M2/M3 已完成；隔离与生产 migration/HDD placement、正式 TaskRun 首次同步、幂等重跑和完整对账均通过。历史回补与 schedule 仍未授权**
首次审计：2026-08-03；复审：2026-08-05、2026-08-07、2026-08-08
截图菜单：基金分红
源文档：[公募基金分红](../sources/tushare/公募基金/0120_公募基金分红.md)
LLD：[公募基金 B4：基金分红 LLD v1](public-fund-b4-fund-div-low-level-design-v1.md)

## 1. 复审结论

`fund_div` 是按公告日发生的分红事件事实，不是无时间快照。源端要求 `ts_code`、`ann_date`、`ex_date`、`pay_date` 至少一个，且没有 `start_date/end_date`。全市场主路径应使用一个 `ann_date` 一个完整 unit；运营输入的日期区间只能由平台按自然日逐日展开。

本轮证明了三项关键事实：

1. `ann_date` 同时返回场外 OF 与场内 SH/SZ，不能按市场后缀裁剪。
2. `ts_code` 历史与对应公告日 fan-out 在两个 O/E 样本上多重集一致；`ex_date/pay_date` 返回的记录也能在各自的公告日结果中复现。
3. 历史公告日存在 **16 个字段完全相同的重复行**。因此，2026-08-05 文档中“全日期签名后没有重复”的结论只能限定在 `20260617`，不能推广到全历史。

第 3 项的处理已拍板：16 字段完全相同只保留一条业务事实，不保存逐行重复次数，不生成 occurrence 身份；运行级 `rows_deduplicated` 只用于对账。业务同时确认正式修订会重新发布公告，而不是原地改写旧公告，因此存储采用 immutable fact ledger：只建 `core_serving.fund_div`，不建 current/observation；只插入新公告事实，不更新或删除旧事实。

## 2. 源端请求矩阵

| 请求 | 结果 | 接入含义 |
| --- | --- | --- |
| 无业务参数 | `50101` 参数校验失败 | 不能做无参 snapshot refresh。 |
| `ann_date=20260617` | 122 行、122 个完整唯一行 | 可作为全市场公告日 unit。 |
| `ts_code=000001.OF` | 29 行、25 个完整唯一行 | 支持单基金历史，但结果本身含 exact duplicate。 |
| `ex_date=20260617` | 130 行，分属 4 个公告日 | 只是查询视角，不能作为完整公告日写入作用域。 |
| `pay_date=20260618` | 137 行，分属 6 个公告日 | 同上，会与公告日 unit 形成重叠。 |
| `ts_code + ann_date` | 匹配样本 2 行/1 唯一，不匹配为 0 | 多参数按 AND 生效；局部结果不能冒充完整公告日源集合。 |
| `ann_date + ex_date` | 22 行 | 多日期参数按 AND 缩小结果。 |
| `start_date/end_date` | 不支持 | range 必须在 planner 内逐自然日展开。 |

主路径不暴露 `ts_code`、`ex_date`、`pay_date`。如果以后需要单基金精确修复，必须先设计能证明完整性且不会把局部结果当作整日源集合的专用路径。

## 3. 字段与分页

必须显式请求并保存全部 16 个字段：

```text
ts_code, ann_date, imp_anndate, base_date, div_proc, record_date,
ex_date, pay_date, earpay_date, net_ex_date, div_cash, base_unit,
ear_distr, ear_amount, account_date, base_year
```

默认与显式 16 字段在 `20260617` 和 `20201215` 两个样本上的行多重集一致。实现仍不得依赖默认字段。

项目 connector 分页实测：

| 公告日 | `limit=50` 页行数 | 不分页基线 | 分页多重集差异 |
| --- | --- | ---: | ---: |
| `20260617` | 50 / 50 / 22 / 0 | 122 | 0 |
| `20201215` | 50 / 50 / 41 / 0 | 141 | 0 |

运行时接受 `limit/offset`，但当前 MCP schema 没有公开这两个参数。实现采用 `offset_limit`、每页重复显式 16 字段、满页后按固定 `page_limit` 递增 offset、短页结束、无任意最大页数；B4-FD-M2 已用项目 source client 复现 `50/50/22` 与 `50/50/41`，并验证 10,000 行正式 2,000 行分页路径。

2026-08-07 对 `19990329/20191104/20201215/20211215/20230110/20260617` 共 476 个源行做字段剖面：`ts_code/ann_date` 均非空；可空最明显的是 `earpay_date` 462 行为空、`ear_amount` 362 行为空、`account_date` 178 行为空。四个数值样本最大为 10 个整数位、4 位小数；`base_year` 的非空样本都是 8 字符完整日期。详见 LLD 9.1；这些是代表样本，不是源端永久上限。

## 4. `ann_date` 主轴证据

### 4.1 按基金历史与公告日 fan-out A/B

| 基金 | `ts_code` 历史 | 公告日 fan-out 后筛基金 | 多重集 missing / extra |
| --- | ---: | ---: | ---: |
| `000001.OF` | 29 行、25 唯一 | 29 行、25 唯一 | 0 / 0 |
| `500001.SH` | 12 行、12 唯一 | 12 行、12 唯一 | 0 / 0 |

两个样本连 exact duplicate 的次数也一致。这个结果支持公告日主路径，但属于有界抽样，不是接口永久 SLA。

### 4.2 自然日而非交易日

- 周六 `20260613` 返回 40 行；
- 周六 `20070414` 返回 7 行；
- `20260614` 返回 0 行。

因此 range 必须逐自然日展开，空日合法且不能当成数据缺失。

### 4.3 当前边界与请求量

- 当前实测最早公告日候选：`19990329`；该日 5 行。
- 安全历史扫描起点建议：当前最早基金成立日 `19980327`。
- `19980327` 至 `20260807` 共约 10,000 个自然日基础请求；按当前 32,356 只基金逐只请求反而至少需要 32,356 个起始请求。
- 年度回补约 365/366 个基础 unit；LLD 将单 TaskRun 上限固定为 366，配额、耗时、HDD/WAL 停止阈值仍须在历史规模审计中量化。

## 5. 两种“重复”必须分开

### 5.1 短键重复不是重复事实

`20260617` 的 `159816.SZ` 有两行，短键 `ts_code + ann_date + imp_anndate + base_date + record_date + ex_date + pay_date` 相同，但：

```text
A: net_ex_date=null,     base_unit=null
B: net_ex_date=20260623, base_unit=9353.7484
```

两行都必须保存。完整事件日期签名必须包含：

```text
ts_code, ann_date, imp_anndate, base_date, record_date, ex_date,
pay_date, earpay_date, net_ex_date, account_date, base_year
```

### 5.2 历史 exact duplicate 是真实源端多重集

| 公告日 | 源行 | 完整唯一行 | 重复的额外行 |
| --- | ---: | ---: | ---: |
| `20191104` | 12 | 6 | 6 |
| `20201215` | 141 | 74 | 67 |
| `20211215` | 160 | 82 | 78 |
| `20230110` | 36 | 21 | 15 |
| `20260617` | 122 | 122 | 0 |

`20201215` 的 67 个重复组均为两次完全相同行，连续三次请求稳定为 141/74。例如 `000001.OF` 的以下 16 字段行原样出现两次：

```text
000001.OF, 20201215, 20201215, 20201211, 实施, 20201217,
20201217, 20201218, null, 20201217, 0.05, 360248.1274,
1270430885.82, null, 20201218, 20201217
```

这些样本没有发现“同一完整事件日期签名、不同完整内容”的批内冲突；但实现仍须 fail-closed 检测，不能把样本结论写成永久保证。对 exact duplicate 固定去重后，`20201215` 的验收恒等式为 `141 fetched = 74 unique + 67 deduplicated + 0 reject`，目标事实表该 scope 为 74 行。

## 6. 发布时间证据

2026-08-07 15:26（Asia/Shanghai）实测：`20260805=24` 行、`20260806=23` 行、`20260807=3` 行。源端会在公告当日出现数据，但尚无证据证明当天何时完整，也未证明后续是否修订。

因此本轮只设计自动任务能力，不创建 schedule。默认执行 D、D-1 或短滚动窗口的选择，必须在多时点观察后另行拍板。

## 7. 当前建议与授权边界

| 维度 | 结论 |
| --- | --- |
| 时间输入 | `ann_date` point；或 `start_date/end_date` range。 |
| unit | range 逐自然日；一个公告日的完整分页结果一个事务 unit。 |
| freshness / audit | 事件型；`bucket_rule=not_applicable`、`audit_applicable=false`。 |
| 存储 | direct-serving immutable fact；只建 `core_serving.fund_div`，全部业务表和索引在 HDD，WAL 保持 SSD；不建 current/observation。 |
| Ops | 公募基金分组；手动与普通 cron/once 能力；无 probe、无 workflow、无 seed。 |
| 过滤 | 首版不暴露 `ts_code/ex_date/pay_date`。 |
| 历史 | 先做年度规模与配额预算，再单独授权回补。 |

### 7.1 B4-FD-M2 隔离验收结果（2026-08-07）

- 全新 PostgreSQL 18.4 隔离集群只监听 `127.0.0.1:55408`。缺少 `gs_raw_cold_hdd` 时，`000130` 在建 schema/table 前失败且版本保持 `000129`；完整隔离库从零迁移到唯一 head `000130`。
- `fund_div` 表、主键和两个二级索引共 4 个 relation 全部绑定隔离 `gs_raw_cold_hdd`；`pg_wal` 仍在集群 data directory，不随 tablespace 迁移。隔离路径只证明 placement contract，生产机械盘真实路径仍须 M3 核验。
- 项目 connector 的 `page_limit=50` A/B 与 2,000 行正式基线多重集一致：`20260617=122`、`20201215=141`，每页显式 16 字段且只传 `ann_date/limit/offset`。
- `20201215` 首次完整对账为 `141 fetched = 74 unique + 67 deduplicated + 0 reject`，`74 saved = 74 inserted + 0 matched`，目标 scope 74；重跑为 `74 saved = 0 inserted + 74 matched`，目标集合不变。
- `20260617` 为 122/122/122/0/122，目标 OF/SH/SZ=`116/4/2`；周六 `20260613=40`，空日 `20260614=0` 合法 no-op。
- 10,000 行容量为 `2000×5+0`，单事务 `1.918s`、端到端 `2.510s`、峰值 RSS `276,873,216` bytes、WAL 增量 `6,912,280` bytes。分页失败、identity/content 冲突、scope regression、partial reject、持久化不完整和数据库异常均原子回滚；同日 advisory lock、异日非阻塞、NUMERIC 精确 round-trip 与 Ops 状态写失败不影响业务提交均通过。
- 隔离阶段未创建 TaskRun、schedule 或 probe；M2 未写生产库。

B4-FD-M2 已通过。

### 7.2 B4-FD-M3 生产验收结果（2026-08-08）

- 生产部署 HEAD=`56779912`，Alembic head 已为 `20260807_000130`；预检时目标表为空，且全局活动 TaskRun、活动日期完整性任务、非空闲业务会话、`fund_div` 历史 TaskRun/schedule/probe 均为 0。migration 已由现有部署流程应用，本轮没有重复执行 DDL。
- 表、主键和两个二级索引共 4 个 relation 均位于 `gs_raw_cold_hdd`。真实路径为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`，挂载设备 `/dev/vdb`、文件系统 ext4，验收时可用约 319 GiB；共享 WAL 未迁移。
- 生产 connector 只读预检 `20201215` 得到 `141 fetched / 74 unique / 67 deduplicated / 0 reject`，单个 2,000 行短页、0 retry、16 个显式字段缺失键为 0，OF/SH=`72/2`。
- 正式 TaskRun `#7653` 首次同步成功：`141 fetched / 74 saved / 67 deduplicated / 0 reject`，`74 inserted / 0 matched`；TaskRun `#7654` 幂等重跑成功：同样 `141/74/67/0`，`0 inserted / 74 matched`。
- 两轮独立源端复核与目标表比较均得到摘要 `6c9e80c38bcacd81ec71e9e0a0c97cf1ebe5390410d67a687799538906af6b37`；双向身份差集、同实体内容冲突和目标 16 字段重算 hash mismatch 均为 0。目标保持 74 行，`ingested_at` 没有被重跑更新。
- 数据状态快照按事件事实展示 `2020-12-15`，没有连续自然日缺口；验收结束后活动任务、schedule、probe 均为 0，六个服务和两个健康接口正常。

B4-FD-M3 已通过。当前仍不授权历史预算/回补或 schedule。

## 8. 拍板结论与后续项

已拍板：

1. exact duplicate 只保留一条唯一事实；业务表无 `source_occurrence_count/source_occurrence_no`，运行级保留 `rows_deduplicated`。
2. 正式修订按新公告保存；采用 immutable fact ledger，不创建 current/observation。相同 identity、相同内容重跑为幂等命中；相同 identity、不同内容以 `write.immutable_fact_conflict` 失败，禁止覆盖旧事实。
3. 数据库同公告日已有 identity 若从本次完整源集合消失，以 `write.immutable_scope_regression` 失败；禁止自动删除既有事实。只有源端和目标 scope 同为空时，空日才成功 no-op。

仍需在对应后续阶段拍板：

4. 历史回补起止日期、限流和 HDD/索引/WAL/耗时停止阈值，放在 B4-FD-M4a 只读预算后决定；单 TaskRun 上限固定为 366 个自然日 unit。
5. 实际自动任务运行时点、维护 D/D-1 以及是否增加短滚动窗口，放在多时点发布观测后决定。

前三项已经关闭设计门禁，B4-FD-M1/M2/M3 也已完成。下一独立授权边界是 B4-FD-M4a 历史规模、配额、耗时与 HDD/索引/WAL 只读预算；历史回补和 schedule 仍须分别授权。
