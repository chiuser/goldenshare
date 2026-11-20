# DG 已确认业务事实登记详细设计

日期 2026-11-20 · 业务规则已确认 · 待开发和验证

上位方案见 [DG 已确认业务事实登记方案](dagster-confirmed-business-facts-plan-v1.md)。本设计的目标是让运营依据公告登记一次，后续基金基础信息同步仍能查到这条事实。首期由 DG 基金状态查询和 ETF 复权因子覆盖检查使用。

## 1. 接入边界和代码落点

**数据集按需接入。** 每个使用方在自己的入口显式指定对象类别、需要的事实类型和业务日期范围。登记模块返回结构化事实，数据集负责解释这些事实对自己的业务有什么影响。首期复权因子只读 `etf / fund_liquidation_started`。基金状态查询同时读取 `fund_delisted`。以后例如基金净值要用清算事实，可接同一批记录，并在净值模块定义自己的规则。

首期在本地 `goldenshare_lake_meta` 维护一个 PostgreSQL 表和一个本地维护命令入口。Tushare Raw 和 ETF Basic 保存源数据，`list_status` 表示来源值。DG 基金状态通过查询接口给出。仓库已依赖 `psycopg2`，Dagster 锁定 1.13.26。实际业务库、认证方式和角色权限在开发前做有界只读核验。 [项目依赖](../../orchestrator/pyproject.toml) · [本地数据库分工](../architecture/大火箭.md)

| 位置 | 实现职责 |
| --- | --- |
| 新增 `orchestrator/sql/create_confirmed_business_facts.sql` | 本地业务表及索引。由具备迁移权限的角色执行。 |
| 新增 `defs/confirmed_business_facts.py` | 枚举、日期和记录类型，表的维护与批量查询。选择最新版本、日期相交和证据校验集中在这里。 |
| 新增 `defs/confirmed_business_facts_cli.py` | 本地维护入口。落实登记、更正、撤销、查历史和查指定日期的基金状态。 |
| `defs/resources.py` | 注册 `confirmed_business_facts` 只读连接。连接对象按需使用。 |
| `defs/io/etf_daily_silver_writer.py` | 现有共用覆盖 SQL 接收生效中的清算事实。源行筛选、写入和对账沿用当前代码。 |
| `defs/checks/etf_daily_checks.py`、`defs/asset_guards/etf_daily_lake_readiness.py`、`defs/sensors/etf_daily_sensor.py` | ETF 复权因子正式覆盖检查和 sensor 文件核验读取事实，复用同一判断。正式检查结果记录实际使用的事实版本。 |

CodeGraph 和当前源码核对了基础信息选择、单日写入、正式检查、sensor 文件核验和初次导入历史数据的 Bootstrap。正式检查与 sensor 文件核验已经调用同一个覆盖函数，在这里加入清算事实即可。ETF 日线和复权因子的成批历史导入属于已结案的 Bootstrap，由其原方案和规则版本管理。本次只用现有单日任务核验 17 日、补齐 18 和 19 日。 [共用覆盖函数](../../orchestrator/src/orchestrator/defs/io/etf_daily_silver_writer.py) · [日常任务](../../orchestrator/src/orchestrator/defs/jobs/etf_daily.py) · [ETF 初次导入与结案记录](dagster-etf-daily-data-onboarding-plan-v1.md)

## 2. PostgreSQL 表与维护操作

### 2.1 建表

表名为 `public.confirmed_business_facts`。以下是迁移 SQL 的表结构。库名、表名和目标角色都在上线前核对。

```sql
CREATE TABLE public.confirmed_business_facts (
    fact_id uuid NOT NULL,
    revision integer NOT NULL,
    action text NOT NULL,
    subject_type text NOT NULL,
    subject_key text NOT NULL,
    fact_type text NOT NULL,
    time_precision text NOT NULL,
    effective_from timestamptz NOT NULL,
    effective_until timestamptz,
    evidence jsonb NOT NULL,
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    recorded_by text NOT NULL DEFAULT session_user,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (fact_id, revision),
    CHECK (
        (revision = 1 AND action = 'confirm')
        OR (revision > 1 AND action IN ('correct', 'revoke'))
    ),
    CHECK (btrim(subject_type) <> '' AND btrim(subject_key) <> ''
           AND btrim(fact_type) <> ''),
    CHECK (time_precision IN ('day', 'timestamp')),
    CHECK (effective_until IS NULL OR effective_until > effective_from),
    CHECK (
        CASE WHEN jsonb_typeof(evidence) = 'array'
             THEN action = 'revoke' OR jsonb_array_length(evidence) > 0
             ELSE false END
    )
);

CREATE INDEX confirmed_business_facts_lookup_idx
    ON public.confirmed_business_facts
       (subject_type, fact_type, subject_key, fact_id, revision DESC);
```

首期程序校验 `subject_type = 'etf'`、六位代码和 `.SH`、`.SZ` 后缀。固定的 `fact_type` 由枚举提供，界面名称和公告文字供人读。每项证据含非空发布机构、公告 URL 和可选公告编号。日级生效时间把上海日期转换成当地零点，使用左闭右开区间。输入空的结束日期表示无已确认的结束日期。操作时间由数据库生成，业务日期由公告决定。

一件事的所有版本沿用同一个 `fact_id`、对象类别、对象代码和事实类型。更正更新生效区间、证据或说明，撤销追加一个末尾版本。对象或事实类型填错时，经撤销后另行登记。首期将同一 ETF、同一事实类型的重叠生效区间视为冲突，运营可以通过更正已有记录处理。同一 ETF 的清算与正式退市是两类事实，可以分别保存。

### 2.2 接口和权限

| 命令／调用 | 输入与结果 |
| --- | --- |
| `register` → `register_fact` | 对象、固定编码、生效日期、可选结束日期、证据和说明。回显新建或已匹配的事实编号和版本。 |
| `correct` → `correct_fact` | 事实编号、看到的版本、修改后的时间与证据、说明。回显新版本或当前已达成的结果。 |
| `revoke` → `revoke_fact` | 事实编号、看到的版本、理由和可选证据。回显撤销版本或已有撤销状态。 |
| `history` → `list_fact_history` | 按事实编号或对象查操作历史，分页返回版本、人员、日期和证据。 |
| `fund-status` → `resolve_fund_status` | ETF 代码、业务日期、经过验证的 ETF Basic 来源行及适用事实。返回来源值、DG 状态及事实引用。 |
| `find_effective_facts` | 对象类别、固定事实类型集合、日期窗口、可选明确代码集合。返回适用的最新事实版本。 |

维护入口采用本项目已有的本地 Python 命令模式。自动任务从本机环境读取 `LAKE_META_POSTGRES_URL`，该身份只有表的读取权限，连接启用只读事务。维护使用独立的 `LAKE_META_POSTGRES_WRITE_URL` 和具名数据库身份。维护角色有查询及所需业务列的 INSERT 权限，`recorded_by`、`recorded_at` 由数据库默认值写入。表与迁移由独立的所有者角色管理。连接串由本地运行环境供值，任务日志只写用途、失败原因和运行范围。资源在被调用时连接，未接入的数据集只加载自己的资源。测试以独立数据库角色和替身核验这条边界。 [现有资源装配](../../orchestrator/src/orchestrator/defs/resources.py) · [Dagster 资源说明](https://docs.dagster.io/guides/build/external-resources/defining-resources)

每次提交都从当前数据库状态开始。登记时，同一对象、同一事实类型已存在内容一致的有效记录就回显它，重叠日期但内容有差异就提示核对。更正时，如果当前有效记录已符合要求就回显该版本。需要追加时须匹配运营所见版本。事实已撤销时回显撤销结果。新写入在同一 PostgreSQL `SERIALIZABLE` 短事务内完成校验和插入，数据库报事务或版本冲突时提示查看最新记录。命令中断后重做同一项操作即可，数据库已提交的有效结果可读回，未提交的事务由数据库回滚。 [PostgreSQL 事务隔离](https://www.postgresql.org/docs/18/transaction-iso.html#XACT-SERIALIZABLE)

### 2.3 查询实现

按对象类别和所需类型筛选，指定单只或一批代码时再按代码裁剪。ETF 复权因子全市场日常检查可查询本批日期内的 ETF 清算事实，再和已有 Basic 名单关联。使用参数传入类型、代码和日期。

```sql
WITH latest AS (
    SELECT DISTINCT ON (fact_id)
           fact_id, revision, action, subject_key, fact_type,
           effective_from, effective_until
    FROM public.confirmed_business_facts
    WHERE subject_type = %(subject_type)s
      AND fact_type = ANY(%(fact_types)s)
      AND (%(subject_keys)s::text[] IS NULL OR subject_key = ANY(%(subject_keys)s::text[]))
    ORDER BY fact_id, revision DESC
)
SELECT *
FROM latest
WHERE action <> 'revoke'
  AND effective_from < %(window_end_exclusive)s
  AND (effective_until IS NULL OR effective_until > %(window_start)s)
ORDER BY subject_key, fact_type, fact_id;
```

日期条件在选出最新版本之后应用。比如更正版本把生效日从 16 日改到 18 日，查 17 日得到空；如果先筛生效日期，17 日会误读旧版本。空结果表示成功查表且这批日期无适用记录。读取失败作为错误返回，不能代表空结果。

基金状态查询按业务日期顺序应用规则。当天已有生效的正式退市事实时给出「退市」，只有生效清算事实时给出「清算中」，两类事实均未命中时使用经过验证的来源值。先读指定版本的 ETF Basic，再对照事实，历史判断以原运行引用为准。来源快照中的 `list_status` 保持其来源含义。

维护入口查询当天状态时，使用现有最新且已核验的 Basic 选择器。查询历史日期时传入当时记录的 Basic 引用，由现有 `validate_etf_daily_basic_reference` 验证文件与指纹。基础信息缺行时回显该代码的来源状态缺失，仍可展示已确认的事实依据。如果来源和事实均无可用状态，则显示待核实。

## 3. ETF 复权因子覆盖规则和输入版本

### 3.1 同一个判断用于正式检查和 sensor 文件核验

沿用当前条件生成可入库名单 `eligible`。在 Basic 中具备匹配的沪深交易所、来源上市状态和已生效的上市日期，代码进入该名单。按交易日将生效的清算事实与名单关联。对 `fund_adj`，必有名单等于可入库名单减去当天已有清算事实的代码。原因是管理员确认从公告的清算生效日**当天起**允许缺省。

| 现有覆盖指标或检查 | 采用的集合 |
| --- | --- |
| `expected_code_count` | 必有名单的大小 |
| `raw_matching_code_count` | 必有名单与实际 Raw 代码的交集大小 |
| `missing_expected_code_count` | 必有名单减实际 Silver 代码 |
| `raw_extra_code_count` | 实际 Raw 代码减可入库名单，保留现有诊断用途 |
| `silver_extra_code_count` | 实际 Silver 代码减可入库名单，仍为阻断项 |

已有阻断检查继续核验源值、字段、唯一键、分区日期和数值范围。清算当天或以后源有有效因子时，依现有筛选和一致性检查入库，Silver 漏写仍有阻断结果。ETF 日线调用原覆盖口径。Bootstrap 计划使用既有的共享规则版本，已经产出的历史文件通过原有证据核验。 [覆盖检查及源数据一致性](../../orchestrator/src/orchestrator/defs/io/etf_daily_silver_writer.py)

现有覆盖函数在 DuckDB 内按交易日和代码匹配清算事实。单日正式检查只查当天，sensor 文件核验按原有窗口批量取一次，逐日传给同一覆盖函数。要生成文件或重跑时，仍从现有作业入口按日期执行。

### 3.2 现有入口怎么用新来源

| 场景 | 输入取得和保存方式 |
| --- | --- |
| 常规单日生成 | `silver_etf_adj_factor` 按现有规则选最新已核验的 ETF Basic，写入后记录该份基础信息的引用。事实用于后续覆盖检查。 |
| 正式检查与已有文件重验 | 通过原有入口选择日期，程序按现有方式找到该日文件和它所用的 ETF Basic。覆盖检查按该日期读取适用的清算事实，结果记下用到的事实编号和版本。 |
| 日常自动任务的文件核验 | 对既有日期窗口批量读一次清算事实。按现有文件核验流程在计算覆盖时使用事实。自动任务继续根据已有核验结果选日期。 |

每次核验只取一次该范围内的事实。正式覆盖检查保存事实编号及版本，空列表也明确记录。公告与运营备注通过登记表的历史查询获得。查表失败时，接入的核验报告「读取已确认业务事实失败」及日期，按现有失败处理。已有批准的特殊历史文件继续用原有证明核验。 [Dagster 分区检查](https://docs.dagster.io/guides/test/asset-checks)

## 4. 530080.SH 的正式验收步骤

开始前核对登记库、目标日期、现有文件及任务状态。在获准的正式补齐期间，先暂停 ETF 复权因子 Silver 的 sensor，确认已提交的相关作业都已结束，然后手动逐个日期执行。

1. 登记 `etf / 530080.SH / fund_liquidation_started / 2026-11-16`，结束日期留空，附天弘基金决议公告。读回编号、版本、证据和上海生效日期。正常同步 ETF Basic 后，用本次同步后经核验的快照查同步当日的 DG 基金状态，读回来源值、清算事实版本和公告。用仍返回 `L` 的来源样本验收时，DG 应显示「清算中」。 [天弘基金公告（转载）](https://qcloud.fund.eastmoney.com/gonggao/530080%2CAN202611141831712627.html)
2. 读回 11 月 16 日的 `530080.SH` 有效因子，再按日期对 17 日已有文件运行 `silver_etf_adj_factor_update_job` 的检查子集。以原来记录的 ETF Basic 和当前适用的清算事实为输入，核对 17 日的实际文件、源行一致性和覆盖检查。 [现有检查子集示例](../../orchestrator/src/orchestrator/defs/bootstrap/etf_adj_factor_history_completion.py)
3. 17 日正式检查通过后，按现有单日任务依次生成 18、19 日。为缺文件日期选取当前任务认可的 Basic，并在执行前同审计所用的 Basic 做代码集合对账。出现其他 ETF 纳入范围变化或源数据变化时，列出差异，核定日期与对象范围后再继续。目标先在 `/Volumes/datasource/data_lake_staging` 生成候选，经现有单文件校验和同盘原子提升进入正式路径。六项检查通过后逐日读回。
4. 检查和读回通过后恢复该 sensor 原有状态。中断后以数据库和正式文件的实际结果为准。已经成功的日期保留。失败日期用新的单日任务重跑。正式文件已生成时，按现有核验复用有效文件或单独补检查。

### 4.1 失败后重做与临时文件清理

登记操作只写 PostgreSQL，正式检查只读取指标文件。18、19 日生成文件时，候选路径由现有写入程序按作业编号和交易日创建。程序遇到可捕获异常会删除本次候选，候选通过校验后原子移到正式位置。强制退出时异常处理可能来不及执行，留下候选。 [候选路径](../../orchestrator/src/orchestrator/defs/paths.py) · [候选校验和清理](../../orchestrator/src/orchestrator/defs/io/etf_daily_silver_writer.py)

手动重跑前，用失败作业的编号和交易日查找其确切候选路径，确认没有作业仍在用。保留错误原因，在获准的清理范围内删除已废弃的候选及对应的空目录，然后用新作业编号重跑。候选清理只针对 `data_lake_staging/etf_daily/operation_id=<作业编号>/silver_etf_adj_factor/trade_date=<交易日>/part-000.parquet`。检查通过的正式文件与 Dagster 作业记录作为已完成证据保留。若正式文件内容有冲突，按现行方式报告，不覆盖。 [数据湖文件清理边界](dagster-data-pipeline-performance-governance.md#63-批量写入必须有原子性和审计)

## 5. 读取与写入范围

以下为 2026-11-20 已有核验的文件和代码计数，供定位本案输入。正常自动任务沿用原 10 个交易日窗口，登记表每个接入批次一次查询。

| 日期 | ETF 复权因子 Raw 唯一代码数 | 原 Raw + Silver + Basic Raw/Silver 文件大小合计 | 验收动作 |
| --- | --- | --- | --- |
| 11 月 16 日 | 2,219 | 271,949 字节 | 核验现有有效记录 |
| 11 月 17 日 | 2,219 | 271,274 字节 | 重验现有文件 |
| 11 月 18 日 | 2,219 | 258,137 字节 | 生成一个目标分区及其候选 |
| 11 月 19 日 | 2,221 | 258,548 字节 | 生成一个目标分区及其候选 |

原输入共 14 个文件、1,059,908 字节，包含四天各一份复权因子 Raw、各一对 ETF Basic 快照及两份已有 Silver。四天 Raw 共 8,878 个代码日期组合。按审计时冻结的 Basic 和同一份 Raw 估算，18、19 日的源行筛选结果分别为 1,720 行、1,721 行。该估算在执行前以真正用于本次运行的 Basic 和源数据一致性对账复核。

| 阶段 | 读写范围 |
| --- | --- |
| 登记与查询 | 新登记一个事实版本，提交一次短事务。已接入的任务按日期窗口批量读表。 |
| 正常执行 | 使用已有 Lake 数据复核 16、17 日，依次补齐 18、19 日。基金基础信息按现有任务同步。 |
| 失败后重做 | 核对失败日期的正式文件，清理废弃候选后重跑该日。保留已通过的日期。每次原子提升限一个文件。 |
| 最终验收 | 对四天做有界读回和代码集合核验。 |
| 停止条件 | 日期超出本次范围、出现未批准的数据差异、目标冲突、挂载异常或磁盘空间不足时停止。 |

## 6. 开发与验收检查表

开发先核验本地数据库、角色、连接配置和资源加载方式，再完成表及命令，然后接入 ETF 复权因子。代码阶段须用项目已锁定的 Dagster 版本在隔离实例验证检查子集、输入引用与目标 materialization 的关联，并同步 ETF 原方案和详细设计的实现附件。等正式接入步骤获准后，按第 4 节顺序执行。

### 6.1 阶段 1 开工前核对（2026-11-20）

**核对完成，可以进入隔离环境开发登记表和维护命令。** 本阶段通过本机 Unix 套接字在只读事务中查询 PostgreSQL 的连接、表和角色目录。正式建表、授权及配置留在正式安装阶段。

| 核对项 | 实际结果和接入办法 |
| --- | --- |
| 业务库 | `goldenshare_lake_meta` 可连接，服务器为 PostgreSQL 18.4。本次事务的只读状态为 `on`。`public.confirmed_business_facts` 尚未创建。 |
| 权限 | 本次核对用的 `congming` 为库所有者且是管理员。首期拟用 `dg_confirmed_facts_owner` 持有表、`dg_confirmed_facts_reader` 供任务读表、`dg_confirmed_facts_maintenance` 向具名维护账号提供查询及追加权限。三个角色尚未建立。开发先在隔离库验证相应权限，正式安装时由管理员配置和验收。 |
| 认证与连接配置 | 本次命令环境中的 `LAKE_META_POSTGRES_URL` 和 `LAKE_META_POSTGRES_WRITE_URL` 均未设置。本地 PostgreSQL 认证文件中匹配业务库的本机连接规则是 `trust`，允许客户端直接指定登录账号。正式投用时应核对实际连接如何验证维护账号身份，并用各自的连接分别验收读写权限。阶段 2 使用隔离库验证。 [PostgreSQL 对 trust 认证的说明](https://www.postgresql.org/docs/18/auth-trust.html) |
| 代码接入 | CodeGraph 和源码确认，正式覆盖检查与 sensor 的文件核验已共用 `audit_etf_daily_basic_coverage`。只给 ETF 复权因子的这两条入口传入事实。历史补全也会调用批量文件核验，因此只读资源由日常入口明确传入，批量核验函数由调用方提供事实。 [正式覆盖检查](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py) · [日常 sensor](../../orchestrator/src/orchestrator/defs/sensors/etf_daily_sensor.py) · [历史补全调用](../../orchestrator/src/orchestrator/defs/bootstrap/etf_adj_factor_history_completion.py) |
| 隔离环境 | 项目已安装 Dagster 1.13.26、`psycopg2-binary` 2.9.12 与 pytest，本机已有 PostgreSQL 的 `initdb`、`pg_ctl` 和 `psql`。 |

### 6.2 开发验证条件

| 验证范围 | 通过条件 |
| --- | --- |
| 表结构和权限 | 两个合法事实类型正确保存。无效编码或倒置日期被拒绝。读角色只能查询，维护身份追加且操作人由数据库赋值。 |
| 按日期查与版本追溯 | 用独立预期验证生效前、当天和结束日。更正、撤销后当前查询正确更新，旧检查仍能查到当时使用的事实版本。 |
| 提交中断后重做 | 分别覆盖数据库已提交和未提交的情况。重做同一项登记、更正或撤销后，数据库只留一份有效业务结果。 |
| 覆盖与源值 | 独立样本覆盖生效日前必有、从生效日允许缺省、源有有效因子必须保留，以及正常 ETF 真缺数和多出非合规代码时继续报错。 |
| 正式检查与文件核验 | 同一日期使用相同的 ETF Basic 和清算事实时，正式检查和 sensor 文件核验的覆盖结果一致。日常按原有顺序选日期。 |
| 数据集按需接入 | 连接被禁用时已接入的检查报告读取失败。ETF 日线、Raw 及未接入数据集能够按自身依赖完成。 |
| 失败清理和重做 | 模拟失败作业留下临时候选。确认能按作业及日期找到并清理指定候选，重跑该日后核对正式文件内容及检查。 |
| 使用说明 | 开发和隔离验证完成后，独立交付《DG 已确认业务事实接入使用说明》。示例使用已验证接口，包含按需接入、维护、事实版本追溯、失败处理及验收。 |

正式 PostgreSQL、Lake 和 Dagster 任务的执行记录按阶段另行核对。阶段 1 已完成只读核对，代码实现和正式验收状态待更新。
