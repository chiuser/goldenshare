# 公募基金 B3：基金经理（`fund_manager`）LLD v1

状态：**B3-M0、LLD 审计与 B3-M1 本地实现/验证通过；B3-M2 尚未开始，未应用迁移、未写数据库、未创建 schedule。**
日期：2026-08-06
上游总览：[公募基金九数据集接入总览与分批推进计划 v1](public-fund-nine-dataset-onboarding-program-plan-v1.md)
依赖：[B0 观察快照直出最小地基 LLD](public-fund-b0-observed-snapshot-foundation-low-level-design-v1.md)、[B2 基金列表 LLD](public-fund-b2-fund-basic-low-level-design-v1.md)
源端发现审计：[基金经理接入发现审计](fund-manager-onboarding-discovery-audit.md)
源接口文档：[基金经理](../sources/tushare/公募基金/0208_基金经理.md)

## 0. 结论与实施边界

B3 只接入 Tushare `fund_manager`。它是“基金经理任职及简历源事实”，不是带有上游稳定人员 ID 的人物主表。主同步固定为**无业务参数、一个无时间 unit 的完整快照**，使用 B0 已实现的 current 完整快照 + observation 观察版本 direct-serving 协议。

源端实测已经证明：显式请求全部 10 个字段，以 `limit=5000` 翻页至 short page，共 `16×5000 + 4357 = 84,357` 行；改用 `limit=4000` 得到 `21×4000 + 357 = 84,357` 行，两次完整行多重集相同。84,357 只是 2026-08-06 的容量基线，不是固定行数 SLA、请求上限或截断阈值。

B3 不是零新增语义。B0 writer 只能拒绝同一 `(source_entity_key, source_content_hash)` 的完全重复行，允许同一实体键带不同内容版本；这对 B1 的机构源事实是有意行为，不能全局改变。B3 必须新增一个默认关闭、仅本数据集启用的声明式“批内唯一键”质量门禁，保证一个完整快照内每个任职实体只出现一次。

本批不做以下事项：

- 不创建或启用 schedule。自动任务频率与 cron/once 时间继续延后，由运营后续单独拍板；这不阻塞 B3-M1 至 B3-M3。
- 不接 probe，不加入 workflow，不自动 seed schedule。
- 不暴露 `ts_code`、`ann_date`、`name` 或日期区间等运营 filters；局部请求不能替换完整 current。
- 不创建人物主表，不因同名自动合并经理；出生年份缺失时不跨基金建立人员身份。
- 不建立到 `fund_basic` 的外键或对象池过滤。`fund_basic` 可用于查询关联，但不得使 Tushare 源事实因对象池差异而丢失。
- 不创建 raw/core/EAV/JSON 镜像，不截断或解析 `resume`。
- 不修改 B0 writer、source client、resolver、unit planner、schedule capability resolver 或前端生产代码的既有主链。
- 不修改 B1/B2 的分页、身份、质量或存储语义。

## 1. 已定口径与硬需求

1. 主请求必须是 `request_params={}` 的无参全量快照；源端对象和公告日过滤只用于诊断，不进入运营输入。
2. 10 个输出字段必须全部显式放入 `source_fields`，每页携带同一字段列表，并全部原样保存到 current 与 observation。
3. 分页固定 `offset_limit`、`page_limit=5000`、并发 1、无最大页数；只有 short page 才表示完整获取成功。
4. 任职实体身份固定为规范化后的 `(ts_code, ann_date, name, begin_date)`；规范化只用于派生键，不改写源字段。
5. 同一完整快照内 `source_entity_key` 必须唯一。相同实体键的完全重复行与内容冲突行都必须在写入前使整个 unit 失败。
6. 人员聚合键只在 `name + gender + birth_year` 三项都非空时生成；任一为空则 `manager_identity_key=NULL`，不自动跨基金合并。
7. `resume` 和其他源字符串全部使用 `TEXT` 保存；不得截断、摘要化或转换为 JSON。
8. current 保存最近一次完整源快照；observation 从接入日起保存同一任职实体的内容变化版本。观察时间不等于公告日或任职生效时间。
9. 表、主键和全部索引固定放 `gs_raw_cold_hdd`；PostgreSQL 集群共享 WAL 保持现有 SSD 配置。
10. 空结果、任一 normalize reject、缺 source field、身份冲突、完全重复源行或分页未到 short page 均不得替换 current。
11. 84,357 行必须通过 B0 writer 的内存、事务耗时、原子回滚和全量对账门禁；不允许以固定页数、固定行数或分页分段提交规避容量问题。
12. Ops 归入既有“公募基金”分组，支持手动、普通 cron/once schedule 与重试；无 probe、无 workflow、无自动任务 seed。

## 2. 源接口真实行为与容量基线

验证日期：2026-08-06。以下行数与分布是当次真实证据，不是永久 SLA。

### 2.1 请求形态矩阵

| 请求形态 | 实际参数 / fields | 结果 | 实现结论 |
| --- | --- | --- | --- |
| 不传业务参数 | `{}`；显式 10 fields | 以 5,000 行翻页共 84,357 行 | 主同步固定一个无参完整快照 unit。 |
| 5,000 行分页 | `limit=5000, offset=0..80000` | `16×5000 + 4357`；17 次请求 | 采用源文档最大页大小；short page 才结束。 |
| 4,000 行交叉验证 | `limit=4000, offset=0..84000` | `21×4000 + 357`；22 次请求 | 与 5,000 行结果的完整 10 字段多重集双向差集均为 0。 |
| 单基金过滤 | `ts_code=150018.SZ` | 3 行 | 可用于只读诊断，不暴露为任务 filter。 |
| 姓名过滤 | `name=吴昊` | 134 行，等于全集同条件子集 | 不作为人物身份或主同步范围。 |
| 公告日点过滤 | `ann_date=20260617` | 89 行且公告日匹配 | 仅是公告点查询，不能证明晚到修订完整。 |
| 未文档化日期区间 | `start_date/end_date` | 与无参前 100 行相同，98 行落在区间外 | 参数被静默忽略，禁止进入 request builder。 |

MCP 小样本的默认字段与显式 10 字段一致；生产仍必须显式请求 fields。项目 connector 的整数 offset 已实测生效；本地文档 `offset` 类型写成 `intint` 是文档拼写问题，不改变实现的整数分页契约。

### 2.2 字段、唯一性与空值

固定 source fields：

```text
ts_code, ann_date, name, gender, birth_year, edu, nationality,
begin_date, end_date, resume
```

84,357 行中每行都存在全部 10 个字段键，完全相同的源行重复为 0。候选身份 `(ts_code, ann_date, name)` 有 419 个重复/冲突组；补入 `begin_date` 后，`(ts_code, ann_date, name, begin_date)` 的重复和冲突均为 0。因此三字段身份被否决，四字段任职身份通过当前真实数据验证。

空值特征：`birth_year` 为空 78,555 行，`begin_date` 为空 1,062 行，`end_date` 为空 38,456 行，`nationality` 为空 10 行；`ts_code`、`ann_date`、`name`、`gender`、`edu`、`resume` 当前无空值。空 `begin_date` 是源事实，不得丢弃；它在身份计算中统一表示为空字符串，但源列仍保存原值。

只有 5,802 行具备非空 `name + gender + birth_year`，可形成 738 个派生人员身份；其余 78,555 行不得靠姓名自动跨基金合并。该派生键是查询辅助字段，不改变 Tushare 任职事实的存储粒度。

### 2.3 容量基线

- 84,357 行紧凑 JSON 为 43,338,698 bytes，约 43.34 MB。
- `resume` 合计 10,049,928 个字符，最大 728，P95 为 214。
- 当前 `DatasetSourceClient` 将全部分页累积在 `rows_raw`；normalizer、writer 与 DAO 还会生成 normalized、snapshot、current、observation 和批次字典，因此 43.34 MB 不能直接等同于进程内存。
- 当前 B0 DAO 在 `SYNC_BATCH_SIZE=1000` 下，对 84,357 行约执行 85 批 existing-key 查询、85 批 observation upsert、1 次 current delete 和 85 批 current insert，即约 256 条主要 SQL，并由 executor 在 unit 末尾只提交一次。
- 5,000 行页大小只减少源请求次数，不改变业务事务必须覆盖完整快照的原则。

## 3. 三层语义拆分

| 语义层 | B3 固定口径 | 代码依据与边界 |
| --- | --- | --- |
| 时间输入 | Ops/TaskRun/Schedule 只提交 `maintain`，不提交公告日、任职日或区间。 | `date_axis=none`、`input_shape=none`、`supported_time_modes=("none",)`；源端日期参数不自动成为运营输入。 |
| 执行 / unit | resolver 生成一个 `none` unit，`request_params={}`；source client 在该 unit 内按 5,000 行翻页至 short page；所有页在一个事务中替换 current。 | 复用 generic no-time planner、`_public_fund_snapshot_params`、`commit_policy=unit`。 |
| freshness / audit | 不存在连续业务日期桶，不要求每日有记录；只展示最近成功快照运行迹象。 | `bucket_rule=not_applicable`、`observed_field=None`、`audit_applicable=false`、`SNAPSHOT_RUN_TRACE`。 |

这里的 `not_applicable` 不只表示退出连续日期 completeness；本数据集还通过 `input_shape=none` 明确不支持时间输入。

## 4. DatasetDefinition、身份与完整性契约

### 4.1 Definition

| 段 | 固定值 |
| --- | --- |
| identity | `dataset_key=fund_manager`、中文名“基金经理” |
| domain | `public_fund / 公募基金` |
| source | `tushare / fund_manager`；10 个显式 source fields；`base_params={}`；复用 `_public_fund_snapshot_params` |
| date_model | `none / not_applicable / none / none`；无 observed field；无 date completeness audit |
| input_model | 无 time fields、无 filters |
| storage | `serving_observed_snapshot_refresh`；current + observation；无 raw/std |
| planning | `no_pool`、无 enum fan-out、`offset_limit`、`page_limit=5000`、并发 1、generic unit builder；无最大页数 |
| normalization | 不做 date/decimal coercion；required=`ts_code, ann_date, name, source_entity_key`；B3 row transform |
| quality | `batch_unique_key_fields=("source_entity_key",)`；其他现有默认不变 |
| capabilities | maintain 支持 manual/schedule/retry，仅 `time_mode=none` |
| observability | `progress_label=fund_manager`、`SNAPSHOT_RUN_TRACE`、无 date audit |
| transaction | `commit_policy=unit`；一次完整快照一个业务事务 |

B1 的 64 行、B2 的 2,000 行 planning 均不修改。`public_fund.py` 新增 B3 专属 planning 字典或内联配置，禁止为了“共享”而把三个数据集收敛到同一页大小常量。

### 4.2 任职实体身份

`public_fund_contracts.py` 只新增 B3 字段 tuple 与纯身份函数，不建立通用人物框架。row transform 继续放在 `src/foundation/ingestion/row_transforms.py`，由 normalizer 既有动态加载机制调用。

任职实体键算法：

1. 仅对键输入做规范化：`ts_code=strip().upper()`，`ann_date/name=strip()`，`begin_date` 的 `None` 或空白统一为空字符串。
2. 将 `[ts_code, ann_date, name, begin_date]` 按稳定 JSON 表示计算 SHA-256。
3. `source_entity_key = "assignment:<sha256>"`，`identity_basis = "assignment_fields"`。
4. 10 个源字段保持原值；`source_content_hash` 继续由 B0 按全部 10 个 source fields 计算。
5. 空 `ts_code/ann_date/name` 由 required field 规则拒绝；空 `begin_date` 允许参与身份。

如果未来源端把 `None` 与空白作为同一任职键的不同内容返回，两行会得到相同实体键但不同内容，批内唯一性门禁必须拒绝整个快照；系统不得任意选择其中一条。

### 4.3 人员聚合辅助键

只有去首尾空格后的 `name`、转大写后的 `gender`、去首尾空格后的 `birth_year` 三项都非空时，才对稳定 JSON tuple 计算 SHA-256，并生成：

```text
manager_identity_key = manager:<sha256>
```

否则保存 `NULL`。该字段只支持未来按可识别人员聚合同一经理的跨基金任职，不是源字段、不是人物主表主键，也不改变 observation 的源事实版本。姓名相同但性别或出生年份不同的人不会合并；出生年份缺失的人即使同名也不会自动跨基金合并。

### 4.4 批内身份唯一性门禁

在 `DatasetQualityPolicy` 增加默认空 tuple：

```python
batch_unique_key_fields: tuple[str, ...] = ()
```

只有 B3 配置 `("source_entity_key",)`。normalizer 在逐行转换、required field 校验完成后，在返回 batch 之前检查该键：

- 首次出现：记录键与全部 source fields 的内容签名；
- 同键且全部 source fields 相同：抛出 `normalize.batch_unique_key_duplicate`；
- 同键但任一 source field 不同：抛出 `normalize.batch_unique_key_conflicting`；
- details 包含 `key_fields`、`key_values`、`first_row_index`、`duplicate_row_index`、两个内容签名和受限样本；不得把完整 `resume` 无界写入错误详情。

两类错误都属于不可重试的 normalize 整批错误，writer 不得被调用。Definition linter 必须拒绝空字段名、重复字段名、以及不在 `normalization.required_fields` 中的 unique key field。

该 contract 是默认关闭的通用质量不变量，不包含 `fund_manager` 分支、不改变 B1/B2。它比修改 B0 writer 的全局实体语义更窄：B1 仍可表达同一机构实体的多条内容版本；B3 则显式声明其单批任职身份必须唯一。B3 current 表还以唯一索引约束 `source_entity_key`，作为数据库侧最后防线；observation 不做该唯一约束，以允许跨次快照保留同一任职的内容版本。

## 5. 字段端到端与表结构

### 5.1 字段映射

源文档将 10 个字段全部声明为字符串。为保持源事实，不将年份或日期列强制转成数据库日期/整数。

| 源字段 | ORM / DDL | nullable | 身份 / 语义 |
| --- | --- | --- | --- |
| `ts_code` | `TEXT` | 否 | 任职实体键输入；源值保留 |
| `ann_date` | `TEXT` | 否 | 公告日期原文；不是任职生效时间 |
| `name` | `TEXT` | 否 | 任职实体和人员辅助键输入 |
| `gender` | `TEXT` | 是 | 人员辅助键输入；不限制枚举 |
| `birth_year` | `TEXT` | 是 | 人员辅助键输入；缺失时不跨基金合并 |
| `edu` | `TEXT` | 是 | 学历原文 |
| `nationality` | `TEXT` | 是 | 国籍原文 |
| `begin_date` | `TEXT` | 是 | 任职身份输入；允许空 |
| `end_date` | `TEXT` | 是 | 离任日期原文，可在后续观察中回填 |
| `resume` | `TEXT` | 是 | 完整简历，不截断、不摘要 |

当前样本无空的 `gender/edu/resume` 仍保留 nullable，以承受未来源端空值而不丢失整行。真正决定实体可接受性的字段只有 `ts_code/ann_date/name` 与派生的 `source_entity_key`。

### 5.2 两张显式列模型

新增：

- `core_serving.fund_manager_current`
- `core_serving.fund_manager_observation`

两表都保存全部 10 个 source fields，以及：

- `source_entity_key TEXT NOT NULL`
- `source_content_hash VARCHAR(64) NOT NULL`
- `identity_basis VARCHAR(32) NOT NULL`
- `manager_identity_key TEXT NULL`
- `created_at`、`updated_at`

两表主键均为 `(source_entity_key, source_content_hash)`，以满足 B0 observation 协议。current 另存 `observed_at`，observation 另存 `first_observed_at/last_observed_at`。current 不增加 `is_current`；表成员本身就是当前完整快照。

索引固定为：

- current：主键；`UNIQUE(source_entity_key)`；`(ts_code)`；`(manager_identity_key) WHERE manager_identity_key IS NOT NULL`。
- observation：主键；`(source_entity_key, last_observed_at DESC)`；`(ts_code, last_observed_at DESC)`；`(manager_identity_key, last_observed_at DESC) WHERE manager_identity_key IS NOT NULL`。

不分区。当前 8.4 万行 current 适合整表原子替换；observation 只在首次观察或内容变化时增长。没有证据表明分区能改善该访问模式，现阶段引入分区只会扩大迁移与索引复杂度。

不建立 `fund_basic` 外键。源端若临时出现基金列表尚未观察到的代码，仍必须保存任职事实；查询层可按 `ts_code` 做可选关联，但不能用关联结果决定入库。

### 5.3 ORM、DAO 与 HDD migration

| 层 | 文件 / 约束 |
| --- | --- |
| ORM | 新增 `src/foundation/models/core_serving/fund_manager_current.py` 与 `fund_manager_observation.py`，注册到 `core_serving/__init__.py` 和 `all_models.py`。 |
| DAO | DAO factory 注册两项既有 `ObservedSnapshotDAO`；不新增数据集 DAO 或专用 writer。 |
| migration | 编码前重新运行 `alembic heads`；本次审计 head 为 `20260806_000126`，新 revision 的 `down_revision` 只能接编码当时真实 head。 |
| HDD | upgrade 的第一项动作验证 `gs_raw_cold_hdd` 存在；不存在则在建表前失败。两表、PK、唯一索引和全部二级索引均显式指定该 tablespace。 |
| WAL | 不迁移、不配置 `pg_wal`；WAL 继续使用 PostgreSQL 集群当前 SSD。验收只记录本次事务的 WAL LSN 增量和磁盘水位。 |
| downgrade | observation 保存源事实；禁止自动 downgrade 删除两表。 |

## 6. B0 writer 容量与事务验收标准

这些标准是 B3-M2 的硬门禁，不是对 Tushare 行数设上限。若源端行数增加，仍必须全部拉取；性能不达标时任务失败并重新设计，不能截断后提交。

### 6.1 验收数据与测量方法

1. 在隔离 PostgreSQL 验证库完成一次真实无参全量同步；行数不得少于当次源端完整分页结果。
2. 容量样本至少覆盖 84,357 行。若真实源端暂时少于该基线，使用确定性 fixture 补足到 84,357；另执行 100,000 行容量 fixture，提供约 18.5% 的增长余量。
3. fixture 必须保持唯一任职实体，并覆盖真实 `resume` 的 P95 214、最大 728 字符量级；禁止用全空短字符串伪造轻量数据。
4. 用专用 one-shot 进程执行 source result → normalizer → B0 writer → DAO → commit 整链路，通过 Linux `/usr/bin/time -v` 或等价 `/proc` 指标记录进程峰值 RSS；不得用紧凑 JSON 文件大小代替进程内存。
5. 记录进程启动前宿主机 `MemAvailable`、PostgreSQL 事务开始/结束时间、SQL 批次数、目标 relation 大小和 WAL LSN 增量。

### 6.2 通过阈值

| 指标 | B3-M2 通过标准 | 失败处理 |
| --- | --- | --- |
| 峰值内存 | 专用同步进程峰值 RSS 同时满足 `<= 1 GiB` 且 `<= 起始 MemAvailable 的 25%` | M2 失败；不得调小数据范围。评审原子 staging/流式归一化方案后重做 LLD。 |
| 数据库事务 | 从第一条 observation SQL 到成功 commit `<= 180 秒` | M2 失败；分析 HDD、SQL 批次和锁等待，不能拆成可见的分页部分提交。 |
| unit 端到端 | 从首个源请求到 commit `<= 240 秒` | M2 失败；区分源端、归一化与数据库阶段后复审。 |
| 提交次数 | 完整 unit 只允许 1 次业务 commit；DAO 内 0 次 commit | 任一页或任一 DAO 自行提交即失败。 |
| 对账 | fetched = normalized = written = current；reject=0；源端/normalized/current 的实体键和内容哈希双向差集均为 0 | 任一差异即失败，不替换 current。 |
| 重复同步 | current 集合不变、observation 行数不增、`first_observed_at` 不变、`last_observed_at/observed_at` 前进 | 不满足即失败。 |

1 GiB 阈值不是预计会用满 1 GiB，而是给当前约 43.34 MB 序列化源数据留下超过 20 倍的对象开销空间，同时拦截无界复制；25% 宿主机可用内存约束保证 worker 不侵占其他服务余量。180 秒参考 B2 生产 32,342 行完整任务约 57 秒的既有证据，为 B3 约 2.6 倍行数留出保守余量；它仍须由隔离 HDD PostgreSQL 实测，而不是靠线性估算宣布通过。

### 6.3 原子性故障注入

在隔离 PostgreSQL 中保存同步前 current/observation 的主键集合与观察时间，然后至少执行两次定向失败：

1. observation upsert 完成后、current delete 前抛出异常；
2. current delete 完成后、current insert 完成前抛出异常。

两次都必须由 executor 执行 session rollback，且回滚后 current/observation 的行数、主键集合和观察时间与失败前完全相同。状态/TaskRun 写入失败不得影响业务事务，但状态链的测试不允许代替上述业务表原子性验证。

如果 B0 writer 在 84,357/100,000 行下未通过门禁，B3 不进入生产 migration。后续方案必须保持“完整快照原子可见”；任何 staging 或流式改造都是新的共享 contract 变更，需要重新做 CodeGraph 全消费者审计和独立 LLD，不在 B3-M1 中临时实现。

## 7. 配置项审计

B3 不新增配置项。

| 配置 / 资源 | 默认 / 当前值 | 来源与持久化 | 消费者 | 生效与运维口径 |
| --- | --- | --- | --- | --- |
| `SYNC_BATCH_SIZE` | 1000 | Settings / env | `BaseDAO`、`ObservedSnapshotDAO` | worker 进程启动时读取；B3 不覆盖。M2 记录实际批次，不能私自为 B3新增环境变量。 |
| `TUSHARE_MAX_CALLS_PER_MINUTE` | 280 | Settings / env 与既有运行时限流链 | Tushare rate limiter | 一次基线 17 个请求；复用全局限流，不新增接口私有限流。 |
| `gs_raw_cold_hdd` | 已有 DB tablespace | PostgreSQL 集群 | Alembic migration、业务 relation | migration fail-closed；隔离与生产均核验 relation tablespace 及生产真实 HDD 路径。 |
| schedule 频率 | 未拍板 | 未来 `ops.schedule` 运营持久化记录 | Ops scheduler | 当前不创建、不 seed；频率延后不阻塞 Definition、表和同步开发。 |

## 8. 消费者审计与 Ops/UI

| 消费方 | B3 处理 | 已审计代码 / 预期改动 |
| --- | --- | --- |
| Definition registry | 注册 `fund_manager` 为 `public_fund` 数据集事实源。 | `definitions/public_fund.py`、`definitions/__init__.py`、runtime registry guard tests |
| manual actions | 自动派生一个无时间、无 filters 的 `fund_manager.maintain`。 | `src/ops/services/manual_action_query_service.py`；只更新精确集合测试 |
| Catalog | 在既有“公募基金”分组新增排序 40 的“基金经理”。 | `src/ops/catalog/dataset_catalog_views.py` |
| workflow | 不新增 workflow step；任何工作流中都不存在该 action。 | workflow registry / API negative tests |
| resolver / planner | 一个 no-time unit、`request_params={}`；无基金、姓名或公告日 fan-out。 | 既有 resolver/unit planner；新增 Definition 计划测试，不改生产代码 |
| request builder | 复用 `_public_fund_snapshot_params`，只返回 `{}`。 | `src/foundation/ingestion/request_builders.py`；不新增参数分支 |
| source client | 每页注入同一 10 fields 与 `limit/offset`，short page 结束。 | 既有 `source_client.py`；用 B3 connector fixture 验证，不改代码 |
| normalizer | B3 row transform；新增默认关闭的批内唯一键质量 contract。 | `datasets/models.py`、`ingestion/linter.py`、`normalizer.py`、`codebook.py` |
| writer / DAO | 复用 B0 observed-snapshot writer 与 DAO；一个 unit 一个 commit。 | 既有 writer/DAO/executor；增加容量、回滚和 B1/B2 回归测试 |
| freshness | 注册 `SNAPSHOT_RUN_TRACE`；不生成日期桶。 | `src/foundation/datasets/freshness_policies.py` |
| cards / snapshot | target 为 `core_serving.fund_manager_current`，raw 为空，展示最近快照运行。 | 既有 projection/API；更新卡片精确集合测试 |
| schedule | capability 只允许普通 cron/once schedule；频率未定不妨碍能力契约。 | 既有 schedule capability resolver；不改生产代码 |
| probe | 未注册 remote probe，API 创建 probe/fallback 请求必须拒绝。 | schedule capability / API negative tests |
| frontend | 只渲染 Catalog 与 automation capability contract；显示“公募基金 → 基金经理”，手动无时间/filters，自动仅普通 schedule。 | 预计无 TS/TSX 改动；API contract + 浏览器只读验收 |
| biz 查询 | 当前不新增面向用户的基金经理查询 API。 | `manager_identity_key` 仅预留并索引，不在 B3 擅自扩业务范围 |

CodeGraph 已覆盖 Definition → resolver/unit → request/source → normalizer → writer/DAO/executor → Ops Catalog/manual/schedule/cards/freshness 的入口与影响面，并对 `DatasetQualityPolicy`、`DatasetNormalizer.normalize` 做 impact 分析。Definition 动态构造、row transform 动态加载和 API 精确集合测试不能被 CodeGraph 完整还原，因此又以当前代码逐文件核验。结论是：B3 只新增一个 foundation 内默认关闭的质量字段；不产生 `foundation -> ops` 反向依赖，不修改依赖矩阵。前端不存在公募基金 action-key 白名单，不需要新增生产前端分支。

## 9. 硬需求追溯账本

| ID | 硬需求 | 代码落点 | 正向测试 | 反向测试 / 真实验收 | 当前状态 |
| --- | --- | --- | --- | --- | --- |
| B3-REQ-001 | 一个无参、无时间、无 filters 的完整快照 unit | Definition、resolver/planner、request builder | plan 只有 1 unit，params={} | time/filter/enum fan-out 配置被 linter/API 拒绝 | M1 自动化通过 |
| B3-REQ-002 | 10 fields 每页显式请求并全部落两表 | contracts、Definition、ORM、migration | 每页 fields 完全相同；两模型列齐全 | 缺任一 source field 时 writer 整批失败 | M1 自动化通过；待 M2 实库 |
| B3-REQ-003 | 5,000 行分页，无最大页数，short page 终止 | B3 planning、source client | offsets 0..80000、末页4357 fixture | 固定页数/未到 short page 不得成功 | M0 实测与 M1 84,357 行 fixture 通过 |
| B3-REQ-004 | 四字段任职身份，源字段不改写 | contracts、row transform | 规范化键稳定且原值往返 | 三字段冲突 fixture、空必填字段 reject | M1 自动化通过 |
| B3-REQ-005 | 单批实体键唯一，冲突不得进 writer | quality policy、normalizer、linter、codebook | 唯一键批次通过 | 同键同内容/异内容分别结构化失败；B1/B2 行为不变 | M1 自动化与回归通过 |
| B3-REQ-006 | 人员键仅 name+gender+birth_year 全非空时生成 | contracts、row transform、ORM | 完整三字段跨基金得到同一派生键 | 缺 birth_year 时为 NULL；同名不同属性不合并 | M1 自动化通过 |
| B3-REQ-007 | resume 和全部源字符串保真 | source fields、ORM/DDL | 728 字符及 Unicode 原样往返 | 无长度截断、无摘要/JSON列 | M1 SQLite/模型通过；待 M2 PostgreSQL |
| B3-REQ-008 | direct-serving current+observation，无 raw/FK | Definition、ORM、B0 writer | 完整快照写两表、内容变化保留版本 | linter拒绝 raw/std；未知 fund_basic code 仍可写 | M1 自动化通过；待 M2 实库 |
| B3-REQ-009 | current 单实体唯一，observation 允许跨次版本 | current unique index、两表主键、quality gate | 同实体内容后续变化替换 current并新增观察版本 | 同批两版本被拒绝、数据库 unique 作最后防线 | M1 自动化通过；待 M2 实库 |
| B3-REQ-010 | 表、PK、全部索引 HDD；WAL留 SSD | migration | 隔离/生产查 relation tablespace 与物理路径 | HDD 不存在时建表前失败；不改 `pg_wal` | M1 migration 静态门禁通过；待 M2/M3 物理核验 |
| B3-REQ-011 | 84,357/100,000 行内存与耗时达标 | M2 容量 harness、B0 writer/DAO/executor | RSS、180s事务、240s端到端均通过 | 任一超限则 M2 失败，不截断、不上线 | 阈值固定，待 M2 实测 |
| B3-REQ-012 | observation/current 单事务原子性 | executor、writer、DAO | 一次 commit，完整对账 | 两个故障点 rollback 后集合/时间不变 | M1 SQLite 故障注入通过；待 M2 PostgreSQL |
| B3-REQ-013 | 公募基金分组，手动 + schedule/retry，无 probe/workflow/seed | Ops Catalog、Definition capability、API | manual 与 cron/once capability可见 | probe/workflow请求拒绝；无 seed 记录 | M1 API 自动化通过；频率延后 |
| B3-REQ-014 | snapshot freshness，无日期 completeness | freshness policies、cards projection | 卡片显示目标表和最近快照 | 不产生 expected date bucket/raw table | M1 API 自动化通过 |
| B3-REQ-015 | 首次同步五段对账且不自动建任务 | M2/M3 release runbook | fetched/normalized/written/reject/current/observation闭环 | 任一差异停止；schedule 数量不增加 | 设计固定，待 M2/M3 |

## 10. 实现文件与测试计划

### 10.1 B3-M1 预计改动文件

- Definition / contract：`src/foundation/datasets/definitions/public_fund.py`、`public_fund_contracts.py`、Definition 注册与 runtime guard。
- opt-in 质量门禁：`src/foundation/datasets/models.py`、`src/foundation/ingestion/linter.py`、`normalizer.py`、`codebook.py`。
- 身份转换：`src/foundation/ingestion/row_transforms.py`。
- ORM / registry：两张 `fund_manager_*` 模型及 `core_serving/__init__.py`、`all_models.py`。
- DAO factory：注册 current / observation 的既有 `ObservedSnapshotDAO`。
- migration：一个新 Alembic revision，创建两张 HDD 表、PK、current 唯一索引及查询索引。
- Ops：`src/ops/catalog/dataset_catalog_views.py` 新增排序 40 item；freshness policy 注册。
- tests：新增 B3 dataset、migration、容量/事务验收 harness，并更新 Definition、runtime registry、Ops API 精确集合测试。
- docs：本 LLD、发现审计、专项总览、`docs/README.md`。

不修改 source client、resolver、unit planner、writer、ObservedSnapshotDAO、executor、schedule capability resolver 或前端生产代码。若编码时发现必须修改这些共享主链，必须停止 B3-M1，回到本文补充消费者审计和方案，不得以接口特例继续。

### 10.2 自动化与真实验收门禁

1. Definition：no-time、无 filters、一个 unit、params={}、10 fields、page_limit=5000、observed snapshot storage。
2. connector：5,000 行分页 offsets、每页 fields、short page结束；交叉 fixture 证明改变页大小不改变完整行多重集。
3. identity：四字段键、空 begin_date、源字段不改写、人员键三字段全非空门禁。
4. quality：同实体同内容和异内容分别失败；错误样本截断；未配置数据集行为不变；linter 反例齐全。
5. writer：重复同步、内容变化、空快照、partial reject、缺字段、完全重复源行、事务 rollback；B0/B1/B2 全回归。
6. ORM/DAO/registry：两表显式列、nullable、PK、current unique、partial indexes、DAO factory 与 table registry。
7. migration：真实 head、HDD fail-closed、两表和全部索引 placement、无 destructive downgrade、无 schedule seed。
8. Ops/API：Catalog排序、无时间手动动作、schedule-only capability、probe拒绝、workflow无条目、direct-serving卡片。
9. 容量：真实 84,357 量级与 100,000 fixture 的 RSS、SQL批次、事务、端到端、重复同步和两处 rollback 故障注入。
10. 工程门禁：Definition lint、架构依赖测试、docs integrity、`git diff --check`；无前端源码改动时不把 frontend build 作为代码门禁，仍做浏览器只读验收。

## 11. 里程碑、发布与回滚

| 阶段 | 内容 | 退出门禁 |
| --- | --- | --- |
| B3-M0 | 源端复审与 LLD | **已完成**：无参全集、10 fields、两种页大小、身份候选、过滤语义、容量与全消费者审计闭环；本文追溯账本无未决开发口径。 |
| B3-M1 | Definition、身份/质量、ORM/DAO、migration、Ops 与单元/集成测试 | 本地定向测试、B0/B1/B2回归、migration静态门禁、Definition lint、docs完整性通过；不触发远程写。 |
| B3-M2 | 隔离 PostgreSQL migration、HDD 与最小真实同步 | 真实全量五段对账、重复同步、84,357/100,000 容量阈值及两处原子回滚全部通过。 |
| B3-M3 | 生产 migration 与首次完整同步 | 生产 tablespace 真实 HDD 路径、首次完整同步五段对账、表/索引/WAL水位记录通过；不创建 schedule。 |
| 后续运营 | 创建自动任务 | 运营另行拍板频率和 cron/once 后手工创建；不是 B3 开发退出条件。 |

生产顺序只能是：部署已验收代码 → 获得生产 migration 授权 → 应用 migration → 核验全部 relation 位于 HDD → 手动首次无参完整同步 → 五段对账与资源记录 → 结束。不得在 migration 中 seed schedule，不得因未确定自动频率阻塞 B3-M1 至 M3。

迁移不提供自动 downgrade 删除源事实。首次同步失败时保留空表或旧 current，修复后重试；禁止 truncate/drop/rebuild。身份冲突、分页未完成或资源门禁失败时必须停止，不得关闭校验或缩小全量口径绕过。

## 12. LLD 审计结论

B3-M1 已完成并通过本地代码门禁。四项关键口径均已落地：无参单 unit 全量快照、5,000 行 short-page 分页、四字段任职身份与批内唯一性 fail-closed、84,357/100,000 行的内存和单事务验收阈值。当前迁移只生成到 Alembic head，尚未应用到任何 PostgreSQL 数据库。

当前没有阻塞编码的产品拍板项。自动任务频率仍是唯一延后运营决策，但 B3 不自动创建 schedule，因此不影响开发、隔离验证或首次生产同步。若 M2 性能门禁失败，新的原子 staging/流式方案将成为独立架构拍板项；在实测失败发生前，不提前改造 B0 共享主链。
