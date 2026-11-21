# DG 已确认业务事实登记详细设计

更新 2026-11-21 · 正式接入与补齐已验收 · 独立使用说明已交付

上位方案见 [DG 已确认业务事实登记方案](dagster-confirmed-business-facts-plan-v1.md)。本设计的目标是让运营依据公告登记一次，后续基金基础信息同步仍能查到这条事实。首期由 DG 基金状态查询和 ETF 复权因子覆盖检查使用。[正式验收](#formal-recovery-results)记录首次接入实绩。[接入使用说明](dagster-confirmed-business-facts-usage-v1.md)供后续数据集使用。

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
| 人工补历史日期 | 指定目标交易日已验收的 ETF Basic Raw、Silver 产出编号。核验并使用这两份文件，写入后记录同样的基础信息引用。 [人工补数配置](#historical-basic-config) |

每次核验只取一次该范围内的事实。正式覆盖检查保存事实编号及版本，空列表也明确记录。公告与运营备注通过登记表的历史查询获得。查表失败时，接入的核验报告「读取已确认业务事实失败」及日期，按现有失败处理。已有批准的特殊历史文件继续用原有证明核验。 [Dagster 分区检查](https://docs.dagster.io/guides/test/asset-checks)

## 4. 530080.SH 的正式验收步骤

开始前核对登记库、目标日期、现有文件及任务状态。在获准的正式补齐期间，先暂停 ETF 复权因子 Silver 的 sensor，确认已提交的相关作业都已结束，然后手动逐个日期执行。

1. 登记 `etf / 530080.SH / fund_liquidation_started / 2026-11-16`，结束日期留空，附天弘基金决议公告。读回编号、版本、证据和上海生效日期。正常同步 ETF Basic 后，用本次同步后经核验的快照查同步当日的 DG 基金状态，读回来源值、清算事实版本和公告。用仍返回 `L` 的来源样本验收时，DG 应显示「清算中」。 [天弘基金公告（转载）](https://qcloud.fund.eastmoney.com/gonggao/530080%2CAN202611141831712627.html)
2. 读回 11 月 16 日的 `530080.SH` 有效因子，再按日期对 17 日已有文件运行 `silver_etf_adj_factor_update_job` 的检查子集。以原来记录的 ETF Basic 和当前适用的清算事实为输入，核对 17 日的实际文件、源行一致性和覆盖检查。 [现有检查子集示例](../../orchestrator/src/orchestrator/defs/bootstrap/etf_adj_factor_history_completion.py)
3. 17 日正式检查通过后，用现有单日任务依次生成 18、19 日，分别指定对应交易日的已验收 ETF 基础信息。目标先在 `/Volumes/datasource/data_lake_staging` 生成候选，经现有单文件校验和同盘原子提升进入正式路径。六项检查通过后逐日读回。
4. 检查和读回通过后恢复该 sensor 原有状态。中断后以数据库和正式文件的实际结果为准。已经成功的日期保留。失败日期用新的单日任务重跑。正式文件已生成时，按现有核验复用有效文件或单独补检查。

### 4.1 失败后重做与临时文件清理

登记操作只写 PostgreSQL，正式检查只读取指标文件。18、19 日生成文件时，候选路径由现有写入程序按作业编号和交易日创建。程序遇到可捕获异常会删除本次候选，候选通过校验后原子移到正式位置。强制退出时异常处理可能来不及执行，留下候选。 [候选路径](../../orchestrator/src/orchestrator/defs/paths.py) · [候选校验和清理](../../orchestrator/src/orchestrator/defs/io/etf_daily_silver_writer.py)

手动重跑前，用失败作业的编号和交易日查找其确切候选路径，确认没有作业仍在用。保留错误原因，在获准的清理范围内删除已废弃的候选及对应的空目录，然后用新作业编号重跑。候选清理只针对 `data_lake_staging/etf_daily/operation_id=<作业编号>/silver_etf_adj_factor/trade_date=<交易日>/part-000.parquet`。检查通过的正式文件与 Dagster 作业记录作为已完成证据保留。若正式文件内容有冲突，按现行方式报告，不覆盖。 [数据湖文件清理边界](dagster-data-pipeline-performance-governance.md#63-批量写入必须有原子性和审计)

<a id="formal-recovery-runbook"></a>

### 4.2 第一阶段的正式执行清单

操作目录为 `lake_console/orchestrator`，使用现有 `.venv/bin/python3 -B`。正式实例为 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，GraphQL 地址为 `http://127.0.0.1:3000/graphql`，代码位置为 `orchestrator`，仓库名为 `__repository__`。先核对挂载、剩余空间、11 月 16、17 日的文件、18、19 日目标路径及相关在途作业。保存 `silver_etf_adj_factor_update_job_sensor` 的原状态，用正式 GraphQL 的 `stopSensor` 暂停，读回 `STOPPED` 并等在途作业结束。

1. **建表及开通权限。** 用本机 PostgreSQL 的 Unix 套接字连接 `goldenshare_lake_meta`。管理员在短事务内用 `sql/create_confirmed_business_facts.sql` 创建表和索引，表归 `dg_confirmed_facts_owner` 所有。建立 `dg_confirmed_facts_reader` 和 `dg_confirmed_facts_maintenance`，本次具名维护账号为 `dg_confirmed_facts_maint_congming`。读角色授予 SELECT，维护组授予 SELECT 和指定业务列的 INSERT。操作者和登记时间由数据库填入。两个登录身份使用 SCRAM。正式库当前的本机默认认证为 `trust`，在现有规则前为这两个新增登录角色配置指定数据库的本机套接字 SCRAM 规则，并拒绝它们经其他本机入口落入 `trust` 规则。仅重载 PostgreSQL 认证配置。用两套独立连接核对实际登录身份、无凭证连接被拒绝以及读、追加权限边界。
2. **让正式 DG 加载连接。** `lake_console/orchestrator/.env` 只配置 `LAKE_META_POSTGRES_URL`，指向读账号，连接串引用 `DAGSTER_HOME` 下权限为 `0600` 的读账号文件 `confirmed-facts-reader.pgpass`。维护命令单独设置 `LAKE_META_POSTGRES_WRITE_URL`，引用同目录独立的维护账号文件 `confirmed-facts-maintenance.pgpass`。凭证由本机保存。现有 `lake-dg-start` 调用的 `dg dev` 会把项目目录交给 Dagster 的环境变量加载器。确认没有会受影响的活动作业后，通过 `reloadRepositoryLocation(repositoryLocationName: "orchestrator")` 刷新代码位置，读回加载状态。17 日正式检查结果中的事实编号和版本是新代码实际连通登记库的验收证据。 [DG 启动入口](../../bin/lake-dg-start)
3. **登记清算。** 使用具名维护连接运行下列命令，随后用只读连接运行同模块的 `history --subject-key 530080.SH`，核对清算编码、生效日期、公告、登记版本和操作人。

   ```sh
   .venv/bin/python3 -B -m orchestrator.defs.confirmed_business_facts_cli register \
     --subject-key 530080.SH --fact-type fund_liquidation_started \
     --effective-from 2026-11-16 --reason '份额持有人大会决议，基金自该日起进入清算' \
     --evidence '天弘基金' 'https://qcloud.fund.eastmoney.com/gonggao/530080%2CAN202611141831712627.html' 'AN202611141831712627'
   ```
4. **先读回 16 日，再只检查 17 日。** 读回 16 日的 `530080.SH`，值应为 `1.0`。使用 GraphQL `executionPlanOrError` 预览 `silver_etf_adj_factor_update_job`，配置为空，`assetCheckSelection` 明确选择该资产的六项检查，`assetSelection` 为空。确认执行步骤只有 `silver_etf_adj_factor_checks` 后，用同一个选择提交 `launchRun`，标签 `dagster/partition=2026-11-17`。读回同一个运行的六项结果，确认它们指向 17 日已有文件、引用原 ETF 基础信息、覆盖检查记录本次事实版本，文件内容保持一致。 [六项检查名称](../../orchestrator/src/orchestrator/defs/run_contracts/etf_daily.py)
5. **核验基础信息更新结果，依次补 18、19 日。** 11 月 21 日已获准同步 ETF 基础信息，Raw、Silver 分别有 1,940、1,931 条，检查均通过。用 `fund-status --subject-key 530080.SH --date 2026-11-21` 复核，DG 显示「清算中」。当天快照把 `159528.SZ` 从 `L` 改为 `D`，若用于历史补数，两日会各漏一条有效源记录。富国基金公告确认 11 月 20 日进入清算。管理员已批准两天各用原交易日已验收的基础信息。按第 4.4 节用 `launchRun` 提交原单日完整作业，依次指定 `dagster/partition=2026-11-18`、`dagster/partition=2026-11-19`。每天等待终态、读回正式文件并核对六项检查、实际输入和事实版本，再推进下一天。 [富国基金公告](https://fund.eastmoney.com/gonggao/159528%2CAN202611191831863513.html)
6. **收尾和恢复原状态。** 核对 16 日原值、17 日文件指纹与六项检查、18 和 19 日正式文件和各自六项检查、清算登记及同步后查询结果。按第 4.1 节处理确认为本次失败留下的候选。原 sensor 为 `RUNNING` 时用 `startSensor` 恢复，原为 `STOPPED` 时维持原状态，完成后查询实际状态。中断时先读回登记、运行、文件和 sensor，按实际进度从尚未完成的一步继续。

11 月 21 日开工前最新的 ETF Basic Raw 对应 11 月 20 日的 1,935 行，原任务每页 5,000 行，按该样本预计当天刷新只需一页。上一份 Raw 和 Silver 文件分别为 122,237 与 118,364 字节，用于估算一次同步的输入规模。18、19 日的复权因子使用已有 Raw 和第 5 节的有界读取范围。重试和最终验收继续沿用第 4.1 节及第 5 节的边界。

### 4.3 第二阶段的文档交付

正式补数和工程验收完成后，原方案与本设计已记下登记编号和版本、正式检查、文件读回及 sensor 恢复结果。随后交付独立的[《DG 已确认业务事实接入使用说明》](dagster-confirmed-business-facts-usage-v1.md)，并从原方案链接。

<a id="historical-basic-config"></a>

### 4.4 人工补数使用交易日对应的 ETF 基础信息

现有 `silver_etf_adj_factor_update_job` 在 `ops.silver_etf_adj_factor.config.historical_basic` 接受一对可选的 Dagster 产出记录编号。日常 sensor 继续使用空配置，选执行当天已验收的快照。人工提供编号时，仅允许早于执行日的交易日，按编号读取一对 Raw、Silver 产出及各自运行的三项原检查。检查必须通过、具有阻断属性并指向所选产出。两份快照的观察日期必须等于目标交易日，Silver 必须引用所选 Raw，路径和内容指纹通过原 ETF Basic 校验。条件不符时在写文件前停止。写入、正式检查和 sensor 文件核验继续使用产出记录里的同一份 ETF Basic 引用。

| 目标交易日 | `raw_storage_id` | `silver_storage_id` | 预计 Silver 行数 | `159528.SZ` 的复权因子、贴水率 |
| --- | ---: | ---: | ---: | --- |
| 2026-11-18 | 8193849 | 8194130 | 1,720 | 1.0、0.5634 |
| 2026-11-19 | 8258042 | 8258306 | 1,721 | 1.0、0.6611 |

行数由原交易日快照与已有复权因子 Raw 关联得出；当时的 Raw、Silver 基础信息各三项检查均已核对通过。每次任务只按编号读两份基础信息的产出与检查，读目标日期的两个基础信息文件及一个复权因子 Raw，生成一个候选并按原流程提升、验收。重跑和读回用同样的日期、文件和记录范围，临时文件按第 4.1 节处理。隔离验证覆盖原日期快照保留源记录、缺少或错误的检查、错配日期在写前拒绝，以及空配置仍选择执行当天快照。上线前确认代码位置可加载、sensor 仍暂停及两个目标无冲突。

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
| 使用说明 | 正式补齐和工程验收完成后，按第 4.3 节记录实际结果，再独立交付《DG 已确认业务事实接入使用说明》。 |

### 6.3 阶段 2 开发与独立审计（2026-11-20）

阶段 2 已交付与本设计一致的建表 SQL、登记与查询代码和本地维护命令。入口为 `python -m orchestrator.defs.confirmed_business_facts_cli`，包含登记、更正、撤销、查历史、查基金状态。维护命令使用独立写连接，历史和状态查询用只读连接。ETF 复权因子覆盖检查和 sensor 接入属于阶段 3。

| 审计项 | 实际结果 |
| --- | --- |
| 表结构和权限 | 在独立临时 PostgreSQL 里实际执行建表，用口令认证连接。读账号有 SELECT 权限，维护账号可追加指定列，数据库自动记录具名维护账号。维护账号无权改写、删除旧版本或覆盖操作人。 |
| 提交中断和历史 | 验证未提交事务退出后可以重做。独立运行维护命令，并用 SQL 直接核对 `530080.SH` 的版本记录。重复登记、更正和撤销最终分别只有一条版本记录，日期边界和更正后旧版本的过滤符合设计。 |
| ETF Basic 更新 | 在隔离 Dagster 实例与临时 Lake 中，先后生成两份内容指纹不同、来源状态均为 `L` 的 ETF Basic 快照。当天查询使用更新后的快照，仍显示「清算中」，同时返回原登记编号和版本。审计发现当天查询曾可显式传旧快照，已纠正，并补回归用例。 |
| 综合验证 | 57 项测试通过，包含登记表真实 PostgreSQL 测试及 ETF Basic 相关回归。Ruff 静态检查、文档完整性与链接检查通过。隔离 PostgreSQL 实例及临时文件已清理。 |

正式 PostgreSQL 建表与授权、正式 Lake 补齐、Dagster 运行和 sensor 操作按后续阶段执行与验收。

### 6.4 阶段 3 开发与独立审计（2026-11-20）

ETF 复权因子的正式覆盖检查和日常 sensor 文件核验都已接入。两处共用覆盖函数。正式检查查询当天，sensor 按现有日期窗口查询一次。ETF 日线、Raw 和特殊历史文件继续按各自原有规则核验。 [共用覆盖函数](../../orchestrator/src/orchestrator/defs/io/etf_daily_silver_writer.py) · [日常文件核验](../../orchestrator/src/orchestrator/defs/asset_guards/etf_daily_lake_readiness.py)

| 审计项 | 隔离验证结果 |
| --- | --- |
| 清算生效日与有效记录 | 临时 PostgreSQL 登记 `530080.SH` 从 11 月 16 日开始清算，临时 ETF Basic 的来源状态仍为 `L`。用六个日期的独立样本运行实际 Dagster 检查和 sensor 文件核验。生效日前缺数会阻断，生效日已有的有效因子原值保留，17 日缺该基金因子可以通过。 |
| 其他缺数与源数据一致性 | 另一只应有数据的 ETF 缺因子、Silver 漏写源端已有的有效因子、Silver 出现可入库名单以外的代码，分别验证为阻断。正式检查和 sensor 文件核验在六个样本日期上的通过结果一致。 |
| 读表失败和更正 | 关闭测试进程的登记库读取配置后，覆盖检查明确报错，另外五项检查仍通过。sensor 记录受阻日期和原因且不申请运行。更正事实后，新检查记下新版本，旧结果保留原版本。到结束日，覆盖检查和批量核验都停止应用该事实。 |
| 文件和正式环境 | 检查前后，临时 Lake 中的 Parquet 文件逐字节相同。正式环境的建表、配置、登记、补齐和 sensor 操作留待后续执行。 |
| 综合回归 | ETF 基础信息、日线、复权因子和历史任务共 405 项测试通过。完善中文错误提示后复跑 36 项直接相关测试，全部通过。登记库未配置时，全仓 Dagster 定义仍可加载，特殊历史文件沿用原来的核验结果。 |

<a id="formal-recovery-results"></a>

## 7. 正式补齐和工程验收（2026-11-21）

正式库 `goldenshare_lake_meta` 已建立登记表。通过实际登录分别验证了任务的只读权限和具名维护账号的追加权限。使用维护命令登记并由只读账号读回 `530080.SH` 清算事实，编号为 `30a33ad9-6684-4824-b818-b7fb05352339`，版本为 `1`，生效于 11 月 16 日上海时间零点。证据为天弘基金的份额持有人大会决议公告。 [天弘基金公告](https://qcloud.fund.eastmoney.com/gonggao/530080%2CAN202611141831712627.html)

11 月 21 日正式同步 ETF 基础信息，Raw 1,940 条，Silver 1,931 条，两层各三项检查通过。用当天验收过的快照查询时，`530080.SH` 的来源状态仍是 `L`，DG 用第 `1` 版登记显示「清算中」。 [ETF 基础信息 Raw 运行](http://127.0.0.1:3000/runs/de9fa945-d0a9-4f2a-b4cb-1fa3e186d67e) · [ETF 基础信息 Silver 运行](http://127.0.0.1:3000/runs/b5f24a17-d8cb-493a-a1a4-a748104f9c2e)

| 交易日 | ETF 复权因子 Silver 文件及验收 |
| --- | --- |
| 11 月 16 日 | 原文件 1,720 条，文件指纹与补数前相同。`530080.SH` 的复权因子仍为 `1.0`。 |
| 11 月 17 日 | 原文件 1,720 条，文件指纹与补数前相同。只重跑六项检查，全部通过，仍使用原 ETF 基础信息。 [正式检查](http://127.0.0.1:3000/runs/208158fb-28d0-47bc-b3c4-ff9d259e4642) |
| 11 月 18 日 | 已用当天验收快照补齐 1,720 条，六项检查全部通过。`159528.SZ` 的复权因子 `1.0`、贴水率 `0.5634`，与 Raw 一致。 [正式运行](http://127.0.0.1:3000/runs/3583ed65-5405-432d-8cd8-e4a95aca12c6) |
| 11 月 19 日 | 已用当天验收快照补齐 1,721 条，六项检查全部通过。`159528.SZ` 的复权因子 `1.0`、贴水率 `0.6611`，与 Raw 一致。 [正式运行](http://127.0.0.1:3000/runs/4911858b-c9d9-4476-9394-3fb4cec5acb5) |

17、18、19 日覆盖检查均记录上述清算事实第 `1` 版，仍应有但缺失的代码数均为 `0`。16–19 日都通过 sensor 使用的文件核验。18、19 日正式文件读回后，确认本次两个候选文件均已移出暂存路径。ETF 复权因子 Silver 的 sensor 由暂停恢复为原来的 `RUNNING`。同期查询确认 ETF 基础信息 Raw、Silver 和 ETF 复权因子 Raw 的三条 sensor 也均为 `RUNNING`。

为保留 `159528.SZ` 而增加的人工补数配置通过 81 项隔离回归。用 CodeGraph 核对了单日任务、ETF 基础信息选择、正式检查和 sensor 文件核验的调用关系。配置只接入 ETF 复权因子单日作业，已有自动流程继续用执行日快照。正式补数和后续接入都按各自获准的范围执行。
