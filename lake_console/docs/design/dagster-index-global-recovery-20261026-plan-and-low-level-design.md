# 国际指数10月4日补探测及近期分区收尾方案与LLD

<a id="report-attachment-cleanup-20261103"></a>

> 2026-11-03附件清理：相关恢复请求/响应、轮询、旧脚本和测试输出等过程附件已删除；下文旧附件清单、数量、命令和裸路径保留为当时记录，不表示文件仍存在，也不要求重跑任务。保留说明及最终结果，具体范围见[清理LLD20.17](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#2017-其余恢复过程附件的清理2026-11-03)。


## 1. 状态和目标

**本轮已完成，结果见§12.4—12.6。** 管理员回复“按照这个顺序推进吧。完成修复。”，批准本方案所列开发、五个writer sensor维护、原失败单日job重执行、必要Silver及恢复原sensor。未扩大日期、工程、数据集或Bootstrap范围；以下方案保留执行依据，实际结果以文末逐步证据为准。

目标是用现有job重新执行2026-10-04失败的补探测；源端若补出记录，再正确更新同日Silver。近期分区由现有sensor追赶，必要收尾不扩大为人工批量补数。

依据：[原接入方案](dagster-index-global-data-onboarding-plan.md)、[原LLD](dagster-index-global-data-onboarding-low-level-design.md)、根AGENTS、[性能治理](dagster-data-pipeline-performance-governance.md)。原方案§12、原LLD§16同步引用本专项。

源参数及字段参照[0211国际指数本地文档](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0211_国际指数.md)，与当前request builder核对；本轮不改接口合同或重新取源。Dagster重执行入口已结合官方文档与当前源码核对，执行时仍须读回job、partition、config和root关系，不凭按钮名称判断正确。

前次“没有证据需要改代码”只覆盖业务取数/合并逻辑。进一步核对发现候选路径和失败留存违反当前规则，**必须先修写入安全，不能按原代码直接执行本次正式补探测**。

## 2. 已有证据和范围

[完整审计证据（附件已清理）](../../reports/index_global_recovery_20261026/README.md#report-attachment-cleanup-20261103)记录2026-10-26 15:39—15:43北京时间的状态，不代表review或执行时状态仍相同。

| 对象 | 已核事实 | 本轮处理 |
| --- | --- | --- |
| 1760分区 | 2022-01-01至2026-10-26自然日；不是A股交易日数 | 不修改注册范围 |
| 10月4日 | Raw 278B、Silver 285B，均零行，对应原检查成功 | 不能把零行直接判成缺数 |
| 10月4日失败 | run `c8a8b9f5-7cd7-49c2-8492-04fcc41d12df`；10月5日10:59补探测因源站DNS失败，4请求含3重试；未进入merge | 原配置人工重新执行一次 |
| 10月23日 | Europe/Americas恢复后成功，Raw/Silver各20行 | 不重复执行 |
| 10月24日 | 所有Raw阶段和Silver已完成，两层零行 | 不因空日重跑 |
| 10月25日 | 审计时Raw前两阶段成功，Silver待最终阶段 | 执行前复用其后自动完成证据 |
| 10月26日 | 审计时尚未追赶到首阶段，Americas要到27日05:30才到时 | 不提前判整日缺失 |

主sensor只回看10天，late-empty只处理最近3个到期自然日，普通失败retry跳过late-empty，所以10月4日不会自行恢复成功。本次未重新查源，不能预先断言该日当前必定零行或有行。

主动正式写入仅限**10月4日Raw和按条件执行的同日Silver**。不重建历史、不全局审计、不做Bootstrap、事件补录或状态清除；近期日期不在本轮人工重跑范围。

## 3. 代码依据与拟改范围

已用CodeGraph `codegraph_explore`核对入口、writer、路径、Silver交接及调用关系，并直接阅读以下现代码。

| 位置 | 当前问题/语义 | 拟处理 |
| --- | --- | --- |
| `defs/paths.py:1235–1279` | 两个global候选路径落在传入root的`raw|silver/index_global/_staging` | 正式root映射到现有`DEFAULT_LAKE_STAGING_ROOT`；测试使用隔离临时根 |
| `assets/index_global_raw.py:394–399,458–460` | 传正式Lake根；启动及失败时删除候选 | 修候选路径，保留失败文件及逐文件checkpoint |
| `assets/index_global_silver.py:275–283,355–357` | 同类问题 | 同上；保留原转换和完整校验 |
| `sensors/silver_index_global_sensor.py:54–55,77–83` | 仅Americas成功触发，run key按日期固定 | late-empty后不依赖自动再跑；按需触发现有Silver job |

拟新增`defs/io/index_global_writer.py`承载本链单文件发布，改动限于本链路径、两层writer、必要调用方和测试。job/asset/check名称、typed config、字段/类型、允许22代码、自然日/五阶段、合并算法、请求策略、sensor去重及retry语义不改，不新增运营配置、不改Prod或其它数据集。

已审查`io/index_daily_writer.py`，它限定三个其它数据集且拒绝零行；`minute_partition_writer.py`带频率和分钟schema，`moneyflow_update_publication.py`带资金流合同，均不能原样用于本链。不扩这些白名单或改它们的语义，只参考已有单文件发布方式；不另造补数入口或通用平台。

调用方还包括临时五阶段序列和`bootstrap/index_global_bootstrap_apply.py`。前者须隔离回归；后者约206行还在正式Lake创建整个临时工作目录，**本轮禁止运行，不扩大为Bootstrap改造**。路径校验须拒绝正式Lake内自定义工作根；不能宣称改完日更writer，历史Bootstrap入口也已合规。其历史数据和证据不删除，恢复该能力另行审计设计。

## 4. 推进顺序和维护窗口

| 步骤 | 动作 | 通过条件 |
| --- | --- | --- |
| 0 | 管理员review，确认开发、维护及单日执行范围 | 本文不替代批准 |
| 1 | 记录并暂停五个相关writer sensor，等待本链已提交任务结束 | 无本链排队/启动/运行/取消中任务；不取消或杀任务 |
| 2 | 按§5开发、§6隔离测试，再加载新代码 | 必要测试通过；现有job/config可用；不安装依赖或试跑正式数据 |
| 3 | 按§7重执行10月4日原失败job一次 | Raw SUCCESS、原检查通过且绑定本次物化 |
| 4 | 按§8决定是否推进同日Silver | 有必要才运行；原检查和单日对账通过 |
| 5 | 按§9收尾，恢复本次暂停且原为RUNNING的sensor | 记录恢复前后状态；失败时停下汇报 |

五个sensor为`raw_index_global_update_job_sensor`、`raw_index_global_retry_sensor`、`raw_index_global_late_empty_sensor`、`silver_index_global_update_job_sensor`、`silver_index_global_retry_sensor`。保存原status/cursor但不修改cursor。自然日注册器和其它数据集sensor不动，尤其不启用此前停止的股票sensor。

暂停必须早于编辑正式管道代码，防止`dg dev`自动加载时新旧writer并行。已有任务不能及时结束则停在步骤1，不绕过并发保护。人工job失败不自动再提交；原fetch已有3次瞬态重试保留，不新增资源限额/中断器。失败后不自动恢复writer sensor放任重试，应报告影响并取得继续处理确认。维护结束恢复sensor也须纳入正式执行授权。

## 5. 写入修正LLD（已实现）

### 5.1 路径与输入

正式Raw/Silver仍是`/Volumes/datasource/data_lake/<raw|silver>/index_global/trade_date=<day>/part-000.parquet`。候选及控制文件改到：

```text
/Volumes/datasource/data_lake_staging/index_global/<asset_key>/
  trade_date=<day>/operation=<root_run_id>/phase=<phase-or-silver>/
    operation.json
    phase_rows.json
    attempt=<unique-id>/part-000.parquet
```

`phase_rows.json`仅用于冻结Raw已成功取回并校验的输入及请求统计；不保存token。稳定操作身份取当前run的root关系，不能从run key反解析；临时序列用调用者提供的稳定运行标识。保持现有两个路径helper入参的含义，以现有正式根/staging常量映射，不新增env、Settings或LakeRootResource配置。内部如需新增参数，全部真实调用方及测试同轮更新，不保留旧候选路径双轨。

正式根必须精确匹配当前路径常量；隔离测试只允许临时根。拒绝旧Lake、符号链接、`..`、非法日期/run/phase、正式Lake内自定义工作根及其它任意磁盘根。根目录须已存在，写前检查挂载、空间和同设备，不自动创建或更换正式根。

### 5.2 单文件写入、中断和继续

单元为一个Raw日期/phase或一个Silver日期。`index_global_writer.py`按正式目标持有文件锁，拒绝同目标并发；不建立跨日期长事务。

1. 在fetch/merge/转换前创建或读取`operation.json`，绑定资产、日期、phase、root run、目标、旧目标身份、输入身份/摘要、schema版本和状态。控制文件在staging内独占临时写入、fsync后原子改名。
2. Raw成功fetch后，先按既有`validate_index_global_phase_rows`核字段/日期/代码/键，再调用现有`normalize_index_global_numeric_values`完成数值归一化，随后冻结输入/请求统计。当前NaN→None发生在merge开头，不能因新增冻结步骤提前到fetch后就跳过它；冻结JSON必须拒绝非标准NaN/Infinity，合法SDK缺失值应先按原逻辑转成NULL，非法数值仍拒绝。回读核对合同、日期和冻结摘要，同操作继续时复用，正常/继续的NULL结果必须一致。没有完整输入的fetch失败不能伪造可继续输入。Silver绑定Raw身份，读取前后变化则停止。

   `phase_rows.json`同样须独占临时写入、fsync、原子改名，再由operation记录其尺寸/摘要并标记取源完成。只有两个文件的身份、范围和完成记录一致才可复用；半成品、摘要不符，或输入已改名但operation尚未确认的中断现场应保留并停止，不能误用或自动再次fetch。另获批准继续时，先按这些事实核定能否补齐记录。
3. 保留现有Raw合并和Silver转换SQL。每次构建独立attempt目录，执行原候选schema、日期、代码、键、有限值和行数完整校验，允许合法0行，不新增每天22代码齐备要求。旧不完整attempt保留，禁止开始即删除。
4. 完整校验后记录`validated`、候选尺寸/SHA256、旧目标身份及输出行数；提升前核输入/目标身份及同设备，持久化`promoting`，再`os.replace`、fsync目录，记录`promoted`。失败保留候选和控制文件，不复制正式数据备份或使用Kopia。
5. `validated`后中断按同操作、相同输入及旧目标身份继续；replace已发生但记录未完成，仅当正式文件内容与候选摘要一致才补齐checkpoint，不重复fetch/merge/替换。输入、候选或目标变化即停，不猜测恢复。COPY中断保留原attempt，用新attempt承接已冻结输入。
6. Raw源为空且旧目标有效时仍保留原数据，记`reused`及身份，不能用空源清空旧行情；新日期没有目标且源为空时按原合同生成0行文件。新的正常phase是新操作，合法晚发布或同键数值更新不能被续跑身份误拦。
7. checkpoint、冻结输入、失败候选保留到验收后按明确清单处理，不清理历史staging。继续执行先核run/operation，须有单独继续依据，不自动新开第二次操作。

只承诺逐文件原子提升。文件恢复不能代替Dagster成功事件，仍经原asset/job及core check正常形成结果。上述控制状态已在本轮实现并完成隔离验证，真实执行边界见§12.5。

### 5.3 实现落点

| 位置 | 变更 |
| --- | --- |
| `defs/paths.py`两个global staging helper | 根映射及路径校验，只改本链 |
| 新`defs/io/index_global_writer.py` | §5.2锁、冻结输入、候选、checkpoint及单文件提升 |
| `assets/index_global_raw.py` | wrapper取得稳定操作身份；保留fetch/merge算法和metadata，委托本链写入协议 |
| `assets/index_global_silver.py` | 绑定Raw，保留转换/reject及候选校验，委托协议 |
| 临时序列/Bootstrap引用及测试 | 核清所有入参消费者；临时序列隔离回归，Bootstrap正式运行仍禁止 |
| job/contract/sensor/catalog/schema | 不改公共行为，不靠改规则补绿 |

## 6. 测试和开发验收

只用现有项目`.venv`和隔离临时根，不读正式instance/Lake或请求源；不做真实性能试验。回归现有`test_index_global_contracts.py`、`test_index_global_raw_io.py`、`test_index_global_silver.py`、`test_index_global_definitions.py`、`test_index_global_p6_sensors.py`、`test_index_global_p6_static.py`及Bootstrap相关测试，新增本链单文件协议测试。执行前确认文件存在，不安装或同步依赖。

| 硬口径 | 必要正反验证 |
| --- | --- |
| 正式候选只能在staging | 两路径helper纯计算断言；坏日期/run、旧根、Lake内自定义根、逃逸/符号链接拒绝 |
| 业务算法不变 | 真实生产者schema为夹具依据，独立字面预期：五阶段合并、同键后值更新、空源保留旧数据、首次0行、Silver日期转换；SDK缺失值先按原逻辑归一化再冻结，正常/继续NULL一致，非法无穷不能进入冻结JSON |
| 错误不污染正式文件 | 缺列、坏类型/日期/代码、冲突键、无穷或校验失败；旧目标与失败候选均保留 |
| 中断后可解释 | COPY中断、validated后退出、replace后记录前退出；继续不重复fetch/已完成提升 |
| 变化判断准确 | 正常下一phase晚发布可更新；同目标并发、继续时输入/候选/目标变化拒绝 |
| 下游规则不偷换 | late-empty不触发Silver、固定日期run key不变；人工通过现有Silver job承接 |

开发后逐条对账代码/测试，定向测试、改动Python的ruff及文档检查通过后才进入正式执行。隔离通过不证明10月4日源端现状，该证据由正式job获取。

## 7. 10月4日Raw执行卡（已批准并执行一次）

- 工作目录：`/Users/congming/github/goldenshare/lake_console/orchestrator`。
- 正式实例：`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`；code location=`orchestrator`。只复用，不初始化/迁移数据库。
- job=`raw_index_global_update_job`，分区=`2026-10-04`。
- 入口：现有失败run页面 **Re-execute all** 一次，沿用`c8a8b9f5-7cd7-49c2-8492-04fcc41d12df`的job、分区和下列原配置；读回新run及root关系。必须先确认修正代码已加载。无法沿用正确入口则停下，不另写取数脚本。

```yaml
ops:
  raw_index_global:
    config:
      trade_date: "2026-10-04"
      probe_phase: "late_empty"
      slot_key: "2026-10-04:late_empty"
      attempt: 0
      late_empty_attempt: 2
```

保留原失败的`late_empty_attempt=2`，不重置成1或制造自动第三次。这里是另获批准的一次人工重执行；保留失败历史/run key/cursor，不删状态绕过去重。维护窗口内五个writer sensor仍停止。

请求仍为`index_global(trade_date=20261004,limit=4000,offset=0,fields=现合同)`，正常0—22行一页，不逐代码下载、不重跑五阶段、不额外先查MCP。沿用现策略：每页最多3次瞬态重试、总请求最多20、阶段预算60秒，不加新运行资源限制。

验收本run SUCCESS、唯一目标物化及原`raw_index_global_core_check`通过并绑定本次物化；读取原source/output count及checkpoint。空源可以成功保留旧0行，不能要求必须新增行才算成功。

## 8. Silver承接

late-empty不自动触发Silver；即使用Americas，固定日期run key也可能已被旧成功运行消费，不能依赖再次自动更新。本轮不改phase、sensor去重或retry。

1. Raw仍0行且文件身份未变，执行前的旧Silver零行/原检查证据也仍有效：跳过Silver，记录原因。
2. Raw补出记录，或同日Silver确实缺失/失效：Raw成功且原检查通过后，用现有`silver_index_global_update_job`的Launchpad只执行该日一次，配置`ops.silver_index_global.config: {trade_date: "2026-10-04", attempt: 0}`。不带sensor run key、不删旧运行记录。
3. 验收Silver SUCCESS、原core check及目标绑定；只对10月4日按现行字段映射作一次Raw→Silver行/键/值对账，允许NULL和0行，绑定输入Raw身份。失败即停，不能恢复retry sensor让它额外重跑。

## 9. 近期分区和收尾

执行前只复用或读取10月23—26日最新阶段/原检查、相关活动run及精确文件stat，不扫1760个分区。25日最终阶段在26日05:30到时，26日最终阶段在27日05:30到时。

近期已完成的日期不重跑；尚未到最终阶段写“待到时”，不判事故。维护结束按原状态恢复sensor，让原cursor继续追赶。已到期仍缺失或追赶失败，列具体日期/phase/失败run供重新review，不把本次授权扩大为近期人工批量补数。

最终只汇总本次run/原检查、checkpoint及目标stat，新增末尾行情读取只保留10月4日必要对账一次；不删除event、不人工写绿。报告说明10月4日是否成功/有无新增行、Silver执行或跳过原因、近期自动完成/待到时/仍失败日期、维护sensor是否恢复，不能宣称全部海外指数都已齐备。

## 10. 预算、失败和清理

预算依据是已有小文件：10月4日两层563B、10月23日两层6390B；不是实测设备I/O。单日≤22行，保守每个Parquet按≤64KiB计；执行前stat明显超出该量级时先解释范围变化，不自行扩大读取。

| 范围 | 请求/job | 读取预算 | 写入预算 | 额外空间 |
| --- | --- | ---: | ---: | ---: |
| 10月4日正常一次，含原检查、候选校验/摘要、控制文件和单日最终对账 | Raw一次、Silver最多一次；正常1页，硬上界现有20请求 | 8MiB | 1MiB | 4MiB |
| 近期收尾 | 最多4日期运行元数据、8路径stat及必要精确文件计数；不触发job/查源 | 4MiB | 0业务数据 | 0 |
| 中断后若另获批准继续一次，含最后验收的合计预留 | 有冻结输入则复用；需重新取源时先说明，沿用原请求策略 | 24MiB | 2MiB | 8MiB |

取源失败、候选/原检查失败、挂载/空间/同设备异常、输入/候选/目标变化或checkpoint异常均停止，不自动人工续跑、不回滚已提升文件。先报告已提升哪个文件、哪些未完成及保留路径，取得继续授权后再处理。单文件锁不为其它数据集新增资源限制或事务。

完成后清理本轮隔离测试临时目录和无用辅助脚本；正式数据、日志、审批/验收证据、checkpoint、冻结输入和失败候选保留。业务staging需清理时另列精确清单确认，不扫描/删除历史staging。

## 11. review要点

请review：先只修本链两处写入安全并隔离验证，再在明确维护窗口内用原job重执行10月4日一次；Raw有变化时才更新Silver；近期按原sensor追赶，不追加全局审计。Bootstrap恢复、Prod、其它数据集和扩大历史范围均不包含。

本节为原review范围记录：当时只交付方案、LLD及代码审计，尚未执行。管理员随后批准按顺序实施，实际开发、验证、加载代码、维护及补探测结果见§12；不把方案文字本身当作验收证据。

## 12. 执行记录

### 12.1 开始前约束与操作入口

已提取硬口径：只处理本链两层writer；候选只能在staging；失败保留；单文件锁/checkpoint/冻结输入；原字段/日期/阶段/合并/NULL规则不变；只重执行10月4日原失败一次；Silver按需；近期不人工重跑；不动其它sensor或已有无关修改。

本机控制入口为`http://127.0.0.1:3000/graphql`，已对照当前安装版`dagster_graphql/schema/sensors.py`核对`stopSensor(id: ...)`、`startSensor(sensorSelector: ...)`。使用`curl --silent --show-error --fail --connect-timeout 5 --max-time 20 -H 'Content-Type: application/json' --data-binary @<本轮精确请求文件> http://127.0.0.1:3000/graphql`，只对§4五个名称操作；不调用cursor更新或reset。原状态、请求/响应及只读DB收尾保存在本轮报告目录。正式Raw仍按§7从失败run页面Re-execute all，不另写业务补数脚本。

当前分支`dev-interface`；`paths.py`已有其它数据集改动，本轮只编辑global相关函数，完整保留原改动。不提交、推送或另建分支。计划文首已标记批准，本节开始时尚未实施代码和正式写入。

### 12.2 开发约束与内部接口

五个writer sensor已按GraphQL原生接口暂停，DB只读核验全部STOPPED、cursor未变、本链活动run和未结束近期tick均为0，证据为`sensors-before.json`、`sensors-stop-response.json`和`maintenance-stopped.json`。开始代码修改前，该门禁已通过。

为落实§5，新增`IndexGlobalPublication`仅在本链writer内部使用：构造参数为Lake根、目标路径、现有helper给出的operation目录、资产/日期/phase/稳定operation身份和必要源路径；上下文持有目标文件锁。`completed()`核验并恢复已validated/promoting/promoted/reused结果，`read_input()`及`freeze_input()`只处理完整且归一化的冻结输入，`new_candidate()`建立独立attempt，`publish(candidate,result=...)`在原候选校验后记录/提升，`reuse(result=...)`记录空源保留目标。结果只保存可JSON化的业务计数及原请求统计，路径由已绑定参数取得，不信任任意checkpoint路径。

Raw wrapper在fetch前开启该上下文，归一化后冻结rows及fetch统计，再把同一上下文交给merge；直接merge/临时序列自行开启上下文，避免重复锁和旧路径入口。Silver绑定同日Raw身份。新的可选内部publication参数仅用于传递此上下文，不新增运营字段；重执行用root run绑定，普通新phase用独立操作，因此正常后续更新仍允许。

逐项测试映射为：路径正反例→两helper；0行/合并/NULL→原Raw与Silver测试；失败与中断/身份变化/并发→新publication测试及writer集成测试；不重复fetch→Raw wrapper隔离测试；原job/阶段/Silver选择不变→既有定义与sensor测试。不得以纯mock测试代替Raw→Silver临时文件集成，也不将正式资源当测试夹具。

### 12.3 正式执行前代码复核补充

隔离回归129项通过后，独立复核发现候选完整校验结束到publish首次取身份之间存在空档：若此时文件被改变，旧调用方式无法证明摘要对应已校验的内容。本步按原“校验通过的同一候选才能提升”硬口径修正内部接口：`publish(candidate,result=...,validator=...)`在取得候选身份后调用原validator一次，确认校验前后身份一致，再计算/绑定摘要；两层删除外部重复调用，仍只做原完整候选校验一次。新增“validator返回时立即改变候选，拒绝且正式目标不变”的隔离负例。只改本链内部调用方和低层测试，不增加全量或第二遍业务校验，不改合同、范围或预算。

同一保护还覆盖promoting控制记录持久化之后：紧邻`os.replace`再次用stat核候选身份，并核源和旧目标身份，防止写控制记录期间变化的候选先被替换、事后才报错；以“保存promoting时改候选”的隔离负例证明在replace前停止。这里只增加元数据核对，不重复读取业务内容。

### 12.4 开发与验证完成

已修改本链两个路径helper、Raw/Silver writer，新增`io/index_global_writer.py`及三个定向测试文件。原取源、合并、行校验、Silver转换/重复处理和候选业务校验函数逐一AST对比无语义变化，见[函数对账（附件已清理）](../../reports/index_global_recovery_20261026/README.md#report-attachment-cleanup-20261103)。未改job、schema、typed config、sensor、Prod或其它数据集writer，`paths.py`原有指数日线改动完整保留。

完整`test_index_global*.py`隔离回归**131项通过**，其中候选变化两个窗口已用负例抓住；Silver elapsed_ms恢复为当前调用包含校验/提升的耗时，相关14项再验证通过。改动文件ruff及工程致命错误基线均通过，CodeGraph sync/status确认仓库根索引最新，未安装依赖。见[验证汇总（附件已清理）](../../reports/index_global_recovery_20261026/README.md#report-attachment-cleanup-20261103)、[最终隔离日志（附件已清理）](../../reports/index_global_recovery_20261026/README.md#report-attachment-cleanup-20261103)。

### 12.5 单日正式执行及Silver跳过

代码位置重载成功后，按§7从原失败run页面点击Re-execute all一次，生成run **`0465cb4b-0af1-4d6e-81d5-ed4c75c5d6f3`**；job、partition、原配置及root/parent均读回一致。run于2026-10-26 17:08:35—17:08:40北京时间执行，**SUCCESS，耗时5.092秒**。本run唯一Raw物化和原core check通过，check target明确绑定本次物化；不是人工补绿或只看run状态。

本次源请求**1次、重试0、返回0行**，输出仍0行；checkpoint状态`reused`，位于批准的`data_lake_staging/index_global/raw_index_global/trade_date=2026-10-04/operation=c8a8b9f5-7cd7-49c2-8492-04fcc41d12df/phase=late_empty`，完整冻结输入和operation保留。Raw 278B、Silver 285B的五字段身份及SHA256与执行前相同，正式Parquet替换0。最后只对这两份文件一次有界计数确认均0行，并确认Silver schema符合现合同，因此按§8.1跳过Silver job，未重复写已有正确空分区。

证据：[启动依据（附件已清理）](../../reports/index_global_recovery_20261026/README.md#report-attachment-cleanup-20261103)、[原生事件（附件已清理）](../../reports/index_global_recovery_20261026/README.md#report-attachment-cleanup-20261103)、[单日验收](../../reports/index_global_recovery_20261026/raw-run-verified.json)。UI显示新run Success及两步Succeeded，旧失败记录仍保留。真实新代码执行只覆盖本次空源分支；非空写入、NULL及中断继续由隔离真实文件测试覆盖，未额外发起真实样本或性能测试。

### 12.6 恢复、近期状态和清理

单日验收后五个原为RUNNING的writer sensor均经原生startSensor恢复，未reset或改cursor，也未启用此前停止的股票sensor。[恢复响应（附件已清理）](../../reports/index_global_recovery_20261026/README.md#report-attachment-cleanup-20261103)及DB读回均确认5项RUNNING。只读记录同时确认原失败恰好新增1个重执行，10月4日最后相关事件已是新run的materialization。

截至**2026-10-26 17:17:42北京时间**，23、24、25日Americas及对应Silver均SUCCESS；24/25日后续late-empty也成功。26日最新自动阶段为Asia第二阶段SUCCESS，该run发生于维护前16:20，不作为新代码非空正式验收证据；后续18:30、27日00:45/05:30尚未全部到时，不能宣称26日全天齐备。不重复人工补近期日期，不创建未来监控任务；见[定向状态读回](../../reports/index_global_recovery_20261026/final-state-readback.json)。

已删除本轮4个明确独占的pytest basetemp目录，4份临时GraphQL请求在逐份摘要核对归档后移除。子任务自检未发现其测试名前缀对应的残留；共享pytest目录/其它任务目录未删。正式数据、历史staging、本次operation/冻结输入、原失败记录和最终证据均保留，[清理明细（附件已清理）](../../reports/index_global_recovery_20261026/README.md#report-attachment-cleanup-20261103)。

本轮没有全局数据审计、Bootstrap、事件补录、Prod更新、其它数据集改造、安装、提交或推送。文档/代码/执行按本专项闭环；历史Bootstrap正式入口仍禁止使用，其既有工作目录问题留待另行批准的专项。
