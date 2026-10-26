# 2026-10-22 DG 数据集恢复方案与记录

状态（2026-10-26，最新）：2026-10-22原109项缺失清单已全部补齐。最后四频分钟九转由原job一次成功执行，4条原检查及物化绑定通过，合94,690行；详情见第50节。21/23日与来源身份未变，两sensor仍STOPPED，23日全部补齐后再启用的TODO保留。没有再次做全局完整性审计；本结论按原清单及本次精确验收销账。代码已提交`9d7028af`，未推送。

## 1. 为什么显示109项缺失

2026-10-24后续授权：管理员已同意先修正股票分钟前复权、MACD/KDJ及state的写入，再按第13节顺序补齐。修改方案和LLD已先落入[专项文档](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md)，原QFQ和MACD/KDJ设计已同步指向。此项更新是授权与方案记录，代码、测试、正式数据完成量另行追加。

沿用2026-10-24 12:50:17（北京时间）的物理审计，不重新执行159项审计。目录180项中159项适用，50项有数据，109项缺失，21项不适用；无后端无法核验或零行文件。109项包括91项目标文件缺失、14项年度文件没有22日记录、4项serving没有当天记录。

缺失按资产、层和频率分别计数：19项是Raw，另外90项是Silver、Gold、指标、状态或发布。一个上游Raw缺失，会使后面多个数据集不能生成。此处说明依赖关系和计数；本轮仅进一步查明主要指数原因，其余链路的具体运行原因仍待各自阶段核实。

| 范围 | 缺失数 |
| --- | ---: |
| 板块分类、成分、行情、技术指标及发布 | 9 |
| 普通指数分钟线 | 19 |
| 指数日线、主要指数日线及日线九转和发布 | 5 |
| 主要指数分钟线、分钟九转、技术指标及状态 | 39 |
| 股票分钟线、前复权、MACD/KDJ及状态、九转 | 35 |
| 市场成交额 Gold 和发布 | 2 |
| 合计 | 109 |

与上次119项缺失比较，ETF分钟线Raw/Silver五频共10项已补齐，没有新增缺失。ETF和七类资金流已有数据，不纳入本次补缺。

## 2. 整体恢复顺序

下表保留最初的阶段划分，主要指数第一阶段已完成。剩余70项现已在第13节细分为11个后续批次，第13节是后续排序的现行依据；这些批次均未执行，不能把最初表中的原阶段编号与后续批次编号混用。

| 阶段 | 范围与顺序 | 缺失数 |
| --- | --- | ---: |
| 1 | 主要指数分钟线完整链：Raw五频5项 → Silver七频7项 → Gold七频7项 → 分钟九转6项 → 技术指标及状态14项 | 39 |
| 2 | 指数日线Lake：raw_index_daily → silver_index_daily → gold_market_major_indices_daily → gold_major_index_daily_nineturn | 4 |
| 3 | 板块Raw/Silver：dc_index Raw及Silver → dc_member Raw及Silver → dc_daily Raw及Silver | 6 |
| 4 | 普通指数分钟线：Raw五频5项 → Silver七频7项 → Gold七频7项 | 19 |
| 5 | 股票分钟线Raw/Silver：Raw五频5项 → Silver五频5项 | 10 |
| 6 | 股票分钟前复权：七频QFQ | 7 |
| 7 | 股票分钟MACD/KDJ和状态、九转：MACD/KDJ指标与状态14项 → 30/60/90/120分钟九转4项 | 18 |
| 8 | 剩余Gold及serving：板块技术指标Gold1项 → 本机CH板块技术指标1项→Prod CH1项 → 主要指数日线九转Prod发布1项 → 市场成交额Gold及Prod发布2项 | 6 |
| 合计 | | 109 |

每一步使用当前已有入口，先确认上游再生成下游。板块成员依赖同日Raw分类；市场成交额依赖五频股票Silver和当天股票日线；前复权MACD/KDJ与九转分别依赖前复权行情和必要前序状态。serving在各自Gold及检查通过后发布。成交额现有job同时生成Gold并写Prod，后续必须按实际写入范围审批与执行。

股票分钟线及年度文件恢复、板块技术指标历史计算放在后续阶段，先测算其读取、写入与续跑开销。板块技术指标现有普通入口从2024-01-02读至目标日，不能作为单日小任务直接启动；本轮不读取这段历史明细。

## 3. 第一阶段：主要指数39项（已完成）

范围只限2026-10-22主要指数分钟线Raw5项、Silver7项、Gold7项、分钟九转6项、技术指标7项、状态7项。主要指数日线及日线九转属于整体第二阶段，不混入本阶段。

已完成当前代码、DG历史、源端有界样本和21日前序证据审计。详细结论和第一阶段方案见第5～10节；方案审计阶段未启动正式任务，获准后的执行记录见第11节，不修改业务代码、原方案或LLD。

## 4. 审计证据

- [物理审计](dg_dataset_audit_20261022_20261024T045017Z.json)
- [缺失分组及旧报告比较](dg_20261022_gap_groups.json)
- [整体恢复顺序](dg_20261022_recovery_order.json)

## 5. 主要指数审计：为什么22日未生成

审计时间：2026-10-24 13:44:20（北京时间）。只查询相关5个job的22日历史（每job最多3条）、活动run、最新运行记录，以及相关sensor的最新持久状态和tick，没有运行sensor evaluator或打开DagsterInstance。

1. 22日五个job均无运行记录，39项也均无对应物化，目标文件全部不存在。这一天尚未启动主要指数恢复，不能把它记录成22日源端取数失败。
2. 最新自动调度记录停留在24日00:11～00:15，仍指向21日。Raw因21日缺4个频率，命中`raw_retry_scope_not_single_frequency`；Silver等待Raw，Gold等待Silver，九转等待Gold。代码先选择最早未就绪日期，再处理该日，所以当时没有越过21日去生成22日。
3. 21日在24日中午已由人工串行恢复，5个job均SUCCESS，95项检查通过。当前最新运行仍是这些21日成功任务；daemon当前未运行，sensor持久状态虽显示RUNNING，其旧cursor没有因此更新。不能把旧cursor当成21日目前仍缺失，也不能认为22日已自动获得推进。
4. 22日专属分区`cn_major_index_mins_trade_days`已经注册，不缺分区；相关5个job没有活动run。Lake已挂载，Lake与staging同设备，当前空闲约2,716.37GiB。

可确认的原因是自动推进此前被21日缺口阻挡，当前没有继续调度；这不是本轮需要修改22日数据合同的证据。其余70项的各自运行原因仍由后续阶段单独核实，不把主要指数原因套用到所有缺失。

## 6. 主要指数现在具备的恢复条件

### 6.1 源端有界核验

主要指数Raw直接调用Tushare `idx_mins`，不从Prod导入。按当前`effective_raw_request_codes_for_date('2026-10-22')`，当天应请求10个代码：

```text
000001.SH 000016.SH 000300.SH 000510.SH 000680.SH
000688.SH 000852.SH 000905.SH 399001.SZ 399006.SZ
```

本轮用`tushareMcp.idx_mins`验证10个代码×5个频率，每次仅请求`2026-10-22 15:00:00`这一时点。50次请求均返回1行，共50行；代码、频率、日期时间、11个显式字段、有限数值及基础OHLC/量额检查均通过。字段顺序为：

```text
ts_code,freq,trade_time,open,close,high,low,vol,amount,exchange,vwap
```

依据是当前Raw writer、运行合同、`asset_guards/major_index_mins_source_probe.py`和本地`docs/sources/tushare/指数专题/0419_股票历史分钟行情.md`。没有修改请求参数或字段合同，没有再次拉取默认字段或整日明细。当前样本只证明各代码各频率收盘数据可取得；正式Raw任务仍须校验当天全部分钟网格、主键、schema、代码覆盖及数值合同，不能预填全日完整。

### 6.2 21日前序与历史输入

复用21日[最终验收](../datasets_recovery_20261021_20261024/final-verified.json)和5份正式任务核验，共95项通过检查。本轮再次查询必要的20项前序输出（6项九转、7项技术指标、7项状态）的最新21日物化，storage_id均与21日报告一致，文件路径、大小、修改时间也未改变；不重跑这95项检查或重扫21日明细。

九转按每个频率最多20个日期读取：现有19日Gold输入，加即将补齐的22日Gold，再使用21日九转结果。本轮仅列目录和stat确认六频共114个既有Gold文件存在，2026-09-17至2026-10-21，总大小925,542字节；没有扫描这些文件内容。

技术指标除了当天Gold、21日技术指标及状态，还需要有限的历史Gold窗口计算MA250/BOLL等。代码`select_major_index_mins_technical_source_dates`使用`ceil(249 / 每日bar数) + 1`选择日期。按21日已验收的源日期窗口向后移动到22日，并调用当前日期选择函数，得到：

| 频率 | 正式计算文件数（含22日） | 已有历史文件 | 历史起日 | 已有文件字节 |
| --- | ---: | ---: | --- | ---: |
| 1分钟 | 3 | 2 | 2026-10-20 | 220,474 |
| 5分钟 | 7 | 6 | 2026-10-14 | 139,919 |
| 15分钟 | 17 | 16 | 2026-09-22 | 152,090 |
| 30分钟 | 33 | 32 | 2026-08-31 | 186,483 |
| 60分钟 | 64 | 63 | 2026-07-17 | 241,398 |
| 90分钟 | 84 | 83 | 2026-06-18 | 278,355 |
| 120分钟 | 126 | 125 | 2026-04-16 | 360,105 |
| 合计 | 334 | 327 | | 1,578,824 |

七个窗口均只缺将由本阶段Gold任务生成的22日目标文件。327个既有文件合计约1.5MiB；本轮只核对文件存在与大小，没有读取历史Gold明细。这是计算所需的有限窗口，不是重建这些历史日期。不能把“依赖前日状态”误写为“完全不读取历史Gold”。

### 6.3 审计结论及边界

当前证据支持使用现有5个原生job恢复本阶段，没有发现必须先改代码的问题。现在39项目标均缺失，尚未出现覆盖冲突。源端整日分钟数据与正式计算结果还没有执行验收，本轮也没有检查其余70项是否具备执行条件。

## 7. 第一阶段具体方案与计划

### 7.1 目标、范围与禁止项

只补2026-10-22主要指数分钟链39个文件及原生DG run/materialization/check事件。正式Lake根固定`/Volumes/datasource/data_lake`，候选固定`/Volumes/datasource/data_lake_staging`；不写Prod，不改21/23日文件，不改sensor/cursor/daemon、动态分区、字段合同或默认配置，不使用runless补绿，不安装依赖，不使用旧Lake或Kopia。

每个job结束后先核对SUCCESS、输出集合、当前文件以及对应原生检查，再执行下一个。九转和技术指标是Gold之后的两个独立分支，按下表串行操作，不把两者写成数据依赖。

| 顺序 | 原生job | 新增文件 | 预期行数 | 原生检查 |
| --- | --- | ---: | ---: | ---: |
| 1 | `raw_major_index_mins_update_job` | 5 | 3,210 | 5 |
| 2 | `silver_major_index_mins_update_job` | 7 | 3,260 | 7 |
| 3 | `gold_major_index_mins_update_job` | 7 | 3,220 | 7 |
| 4 | `gold_major_index_mins_nineturn_update_job` | 6 | 810 | 6 |
| 5 | `gold_major_index_mins_technical_daily_update_job` | 14 | 技术指标3,220＋状态70 | 70 |
| 合计 | 5个job | 39 | 13,790 | 95 |

预期行数来自当前交易时段合同、10个有效代码与21日同合同实际结果；最终应以22日原生完整检查为准。与21日不同，22日没有1分钟Raw可复用，故5个Raw频率都要取数。Raw各频率预期分别为1分钟2,410行、5分钟490行、15分钟170行、30分钟90行、60分钟50行。

Silver 90分钟从30分钟、120分钟从60分钟派生；Gold按当前标准K线合同生成，非1分钟不输出独立09:30，所以Gold行数与Silver存在合法差异。技术指标和状态属于同一个multi_asset，每个频率必须成对生成，不能只选其中一个。

### 7.2 正式执行前的必要检查

获得本阶段明确执行授权后，只追加以下检查，不再重复本轮50个源端样本或159项完整性审计：

1. 相关5个job无活动任务，人工维护窗口没有并发写入，daemon继续保持当前停止状态；本阶段不启停服务。
2. 22日分区仍已注册，39个目标仍全部缺失；若出现新增文件或物化，停止使用整job计划，先核对变化范围，不能覆盖现有结果。
3. Lake与staging挂载、权限、同设备和空间满足要求；21日20项必要前序物化和文件状态仍与本轮证据相同。
4. 复用本轮有限历史文件清单，仅检查边界和文件状态有无变化；正式计算由原生writer执行合同检查，不额外全历史审计。

### 7.3 已批准的完整命令

工作目录：`/Users/congming/github/goldenshare/lake_console/orchestrator`。正式`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，使用现有登录环境和项目`.venv/bin/dg`，不通过uv自动同步。命令依据为本地`dg launch --help`及已阅读的Dagster skill `references/cli/launch.md`，21日已用相同原生入口完成正式运行。

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job raw_major_index_mins_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job silver_major_index_mins_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job gold_major_index_mins_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job gold_major_index_mins_nineturn_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job gold_major_index_mins_technical_daily_update_job --partition 2026-10-22
```

每条命令保存stdout/stderr合并日志、run_id、开始结束时间与核验JSON；不能把5条命令放入无条件继续的批处理。方案审计阶段这些命令均未执行；获准后的实际执行记录见第11节。

## 8. 性能预算、失败和中断

### 8.1 实际规模与预算

| 项目 | 计划与依据 |
| --- | --- |
| 工作量 | 1日、10个指数、5个Raw频率；39个新文件、39项物化、95项检查 |
| 源端请求 | 正式取数正常50次：每个代码每个频率一天小于8,000行；3,210行Raw。审计50次收盘样本已完成，不重采样 |
| 请求与超时 | 每频率沿用`TushareRequestPolicy`：最小间隔0.13秒、最多3次重试、最多1,200次请求、300秒累计预算；该预算按频率生效，不是整个job的300秒硬保证。若出现重试、缺数据或异常长请求，记录原因，不能私自放宽 |
| Silver/Gold | 当天小文件，派生、归一化、聚合与校验使用当前DuckDB实现，保持现有频率和字段合同 |
| 九转输入 | 现有114个Gold文件925,542字节＋22日六频Gold＋21日六频九转；每频率最多20个日期，正式计算可能多次扫描，不把文件唯一大小当总I/O |
| 技术指标输入 | 现有327个Gold文件1,578,824字节＋22日七频Gold＋21日七频技术指标/状态；最多126日，不读取其它频率或全部历史 |
| 内存和临时空间 | 使用现有DuckDB资源，每连接16GB、4线程上限；不新增配置。21日同范围39个最终文件共935,716字节，22日预计相近；本阶段输出、候选与异常现场新增预算64MiB，远小于当前空闲空间；超出预估先停止后续任务复核，不自动清理正式文件 |
| 耗时 | 21日同链原生job时间合计约34.87秒（当时1分钟Raw复用）；22日多10次源请求，计划正常总墙钟3～8分钟（含CLI装载、串行核验和记录），10分钟作为人工复核告警，不据此强杀运行中的原子提升或自动重试 |
| 每步核验 | 只读该run有界事件，每次最多500条；核对本步文件、物化和95项检查的正确对应，不额外执行同一套公式或全文件差集 |
| 最后验收 | 对39个目标一次统一读回行数、schema和文件hash；核对21/23日同范围路径stat未变化；按缺口集合减去39项，不重跑159项全局审计。参照21日41个文件最终核验0.726秒，预计秒级，超过30秒先定位原因 |

### 8.2 按当前writer处理失败，不能无条件整job重放

- **Raw**：已有合格目标可完整校验后复用，且该频率不再请求源端；已有非法目标会拒绝覆盖。单频失败后先看各频率发布与检查事实，再决定是否重跑Raw job；只对剩余频率取数，累计记录请求和耗时。
- **Silver**：已有目标通过当前校验后可复用；未通过则停止，不能删除或覆盖来通过检查。
- **Gold**：当前writer拒绝已有目标。若job部分成功，不能直接重跑整个七频job；先列已完成与缺失频率，另行确认只执行缺失资产及检查的范围。
- **九转**：当前writer会以`os.replace()`替换目标，不提供Raw同样的已有目标复用保护。因此首次执行必须确认六个目标全部缺失；若部分成功后中断，停止，不自动重跑整个六频job或覆盖已有成功文件。
- **技术指标与状态**：当前writer拒绝任一目标已存在；两个文件分别原子提升，不是成对整体原子。若只提升一个文件后失败，保留正式文件、记录事实并停止，不能删除其中一个文件、强行重跑或宣称已有通用续跑能力。需要针对实际残留补充处理方案。
- **候选与日志**：保留已发布文件、DG失败记录和本次操作日志；现有writer在异常时可能自行清理staging文件，不能承诺所有候选现场都会保留。本阶段不新增备份、快照、清理脚本或删除正式数据动作。
- **检查失败**：有文件而检查失败时停止对应后续链路，不补runless绿事件；若只是事件写入或核验失败，先核对文件与当前物化，不能把“没有观测成功”直接当成“文件没写入”而重采全部数据。

失败后的必要动作限定为当前失败job、其输出和必要输入的有界读回；已完成步骤不重复源端请求。Gold/九转/成对指标出现部分发布时，本计划不授权额外覆盖或删除，必须先补充具体处理范围及预算后再执行。

## 9. 验收与本轮对账

本阶段将以下条件全部满足才记为完成：

1. 5个原生job均SUCCESS；39个输出均为22日预期资产，不带入日线、股票、ETF、资金流或serving。
2. 95项要求检查全部通过且对应当前同日物化。技术指标和状态成对齐备，连续性使用21日结果。
3. 39个物理文件统一读回有正行数，schema符合当前catalog，行数与物化metadata和时段合同一致；同一文件不反复做深度差集。
4. 21/23日文件状态未改变，没有活动恢复run，不修改daemon/sensor/分区/cursor。
5. 当前主要指数39项缺口清零；整体缺失由109项预期降至70项。其余70项不自动视作已验收，不在第一阶段继续执行。

方案审计阶段的只读核验已完成，当时未执行正式恢复；后续正式执行另记第11节。没有修改业务代码、配置或原方案/LLD，没有安装依赖、执行单元测试或提交Git；既有测试只作为代码语义依据，不把旧测试数量作为22日正式通过证据。CodeGraph已用于主要指数Raw、sensor和九转调用链审计，随后核对当前资产、writer、检查合同及实际证据。没有发现需要先修改代码才能开始本阶段的证据，但中断后的特殊残留处理不在本轮执行范围内。

## 10. 证据与后续记录位置

- [主要指数只读审计](major-index-readonly-audit.json)：22日无run/物化、分区、39目标、21日前序、sensor旧状态及文件环境。
- [50个收盘样本](major-index-source-probes.json)：完整参数、显式11字段、响应与身份检查；不证明全日网格。
- [技术指标历史文件范围](major-index-technical-input-stat.json)：当前函数选取的334个目标输入路径，327个既有文件stat；不含历史明细。
- [第一阶段数量与边界](major-index-stage-plan.json)。
- [只读审计脚本](major-index-readonly-audit.py.txt)：只作证据归档，不接入Definitions或自动运行。
- 当前代码位置：`defs/assets/major_index_mins_raw.py`、`major_index_mins_silver.py`、`major_index_mins_gold.py`、`major_index_mins_technical.py`、`major_index_nineturn.py`；`defs/io/major_index_mins_raw_writer.py`、`major_index_mins_silver_writer.py`、`cn_a_gold_minute_writer.py`、`major_index_mins_technical_writer.py`；`defs/major_index_nineturn.py`；`defs/sensors/major_index_mins_sensor.py`及相应Gold/九转/技术指标sensor；5个job定义保持现行选择。

第一阶段已获准并完成，预检、逐步操作与最终验收见第11～12节；第2～8阶段没有执行。第一阶段计划JSON保留制定时的状态，实际执行结论以第12节和执行汇总为准。


## 11. 第一阶段正式执行记录

管理员已明确批准按第7～9节恢复2026-10-22主要指数39项，每步通过后再继续；完成本阶段即停止，不进入其它阶段。执行命令、工作目录、正式DAGSTER_HOME和读写边界沿用第7节。复用21日只读核验方法，限定为本日39项和5个job；读回脚本仅作预检和记录，不承担业务写入或任务启动。[本次只读核验脚本](execution-readback.py.txt)。

执行前先核对目标缺失、任务空闲、21日前序与有限历史文件状态、空间和同设备条件；不会重复50次源端抽样或159项完整性审计。以下逐步追加实际记录，未执行步骤不预填成功。

### 11.1 正式执行前检查

[执行预检](execution-preflight.json)通过：39个目标全部缺失且无同日物化，5个job均无活动run，daemon保持未运行，22日分区已注册；21日20项必要前序的物化与文件状态未变化。只对现有清单中的343个不同历史上下文文件做stat核对，无历史行情明细读取；空间约2,716.37GiB，Lake与staging同设备。没有重复源端收盘抽样或全局完整性审计。

按第7.3节逐条命令执行，stdout和stderr分别合并保存到对应job名称的`.log`文件，每步核验另存JSON；没有使用无条件串行批处理。

### 11.2 Raw五频

正式任务 `2413a958-ad19-425b-9f9e-c4b3c658a4a0` SUCCESS，用时 10.974 秒；5个新增文件共3,210行，5项检查全部通过且绑定当前同日物化。各频率行数为1分钟2,410、5分钟490、15分钟170、30分钟90、60分钟50。实际源请求50次，重试0次，整日网格、代码覆盖及数值合同通过。[本步核验](raw_major_index_mins_update_job-verified.json)；[执行日志](raw_major_index_mins_update_job.log)。

### 11.3 Silver七频

正式任务 `7a43ac85-45ea-47da-bdf8-828361719593` SUCCESS，用时 4.794 秒；7个新增文件共3,260行，7项检查全部通过且对应当前物化。原生五频3,210行，90分钟30行，120分钟20行。[本步核验](silver_major_index_mins_update_job-verified.json)；[执行日志](silver_major_index_mins_update_job.log)。

### 11.4 Gold七频K线

正式任务 `c99104bb-6180-452e-86e6-da936b4e0d52` SUCCESS，用时 2.666 秒；7个新增文件共3,220行，7项检查全部通过。非1分钟频率按现有合同合并竞价锚点，行数与Silver的差异符合方案。[本步核验](gold_major_index_mins_update_job-verified.json)；[执行日志](gold_major_index_mins_update_job.log)。

### 11.5 分钟九转六频

正式任务 `fdf65e9f-d513-495c-835b-bb5a53a9660b` SUCCESS，用时 6.611 秒；6个新增文件共810行，6项检查全部通过且对应当前物化。只读方案约定的20日以内Gold窗口与21日九转，不改写历史结果。[本步核验](gold_major_index_mins_nineturn_update_job-verified.json)；[执行日志](gold_major_index_mins_nineturn_update_job.log)。

### 11.6 技术指标及状态七频

正式任务 `09e38e91-d939-4bb3-88db-31b910c412ea` SUCCESS，用时 9.942 秒；技术指标7个新增文件共3,220行，状态7个新增文件共70行，70项检查全部通过。全部沿用21日前序；实际读取各频率方案约定的有限历史窗口，仅发布22日结果。[本步核验](gold_major_index_mins_technical_daily_update_job-verified.json)；[执行日志](gold_major_index_mins_technical_daily_update_job.log)。


## 12. 第一阶段最终结果与停止位置

最终验收时间：2026-10-24 14:04:45（北京时间）。2026-10-22主要指数分钟链原缺39项全部恢复，39个新文件共13,790行；5个正式job全部SUCCESS，95项不同检查目标全部通过，39项物化与实际文件一致。没有失败、取消、重试源请求或任务重跑。

| 范围 | 新增文件 | 行数 |
| --- | ---: | ---: |
| Raw五频 | 5 | 3,210 |
| Silver七频 | 7 | 3,260 |
| Gold七频 | 7 | 3,220 |
| 分钟九转六频 | 6 | 810 |
| 技术指标七频 | 7 | 3,220 |
| 技术指标状态七频 | 7 | 70 |
| 合计 | 39 | 13,790 |

### 12.1 正式任务及核验

| 顺序 | job | run_id | 检查数 | 任务耗时（秒） |
| --- | --- | --- | ---: | ---: |
| 1 | `raw_major_index_mins_update_job` | `2413a958-ad19-425b-9f9e-c4b3c658a4a0` | 5 | 10.974 |
| 2 | `silver_major_index_mins_update_job` | `7a43ac85-45ea-47da-bdf8-828361719593` | 7 | 4.794 |
| 3 | `gold_major_index_mins_update_job` | `c99104bb-6180-452e-86e6-da936b4e0d52` | 7 | 2.666 |
| 4 | `gold_major_index_mins_nineturn_update_job` | `fdf65e9f-d513-495c-835b-bb5a53a9660b` | 6 | 6.611 |
| 5 | `gold_major_index_mins_technical_daily_update_job` | `09e38e91-d939-4bb3-88db-31b910c412ea` | 70 | 9.942 |

### 12.2 最后一次读回与实际开销

[最终验收](major-index-final-verified.json)只对本次39个目标统一读回一次行数、schema和压缩文件hash：均有正行数，行数符合已批准时段合同与物化metadata，schema符合当前catalog。95项原生检查已逐步确认通过且绑定当前同日物化；最后没有重复执行公式或全文件差集。

正式源请求50次、重试0次，五频Raw共3,210行；没有重复执行此前50个收盘样本。技术指标实际输入文件数和日期逐频率匹配方案，全部使用21日前序。21/23日同范围78个路径的存在性、大小、mtime均未改变；343个既有历史上下文文件的stat也未改变。相关5个job无活动run，daemon继续保持未运行，没有修改sensor、cursor或分区。

原生任务时间合计34.987秒；包括CLI装载、串行核验和记录的总墙钟275.469秒，符合3～8分钟预算。最终读回0.672秒，39个文件合计940,069字节，低于64MiB输出/候选预算。没有触发超预算停止或失败续跑处理。CLI仍提示当前未激活虚拟环境，实际全程使用项目现有`.venv/bin/dg`，不改环境配置或安装依赖。

### 12.3 剩余范围与执行边界

以执行前109项缺失清单扣除本次实际恢复39项，剩余70项：52项文件缺失、14项年度文件缺22日记录、4项serving无22日记录。[剩余清单](remaining-missing-after-major-index.json)注明这是复用原审计后的集合对账，不是重新审计其余数据集；没有重跑159项全局审计。

本轮仅执行已批准的5个job，写22日39个目标、对应staging及原生DG事件。没有修改业务Python代码、配置、原方案/LLD、Prod、其它日期、其它数据集或服务状态；没有runless事件、安装、Git提交。临时只读核验脚本仅归档为文本证据，没有接入Definitions。

**第一阶段完成后已停止，未推进第2阶段或其余70项。** 后续仍需按原整体顺序先审计对应来源、成本和前序条件，再获得相应阶段执行授权。

[执行汇总](major-index-execution-summary.json)记录实际数量、开销和停止边界；[执行预检](execution-preflight.json)保留执行前事实。本轮验收依据为真实正式任务、95项原生检查和限定39文件的读回，没有新增或运行单元测试。文档完整性检查、报告链接及数量对账通过。


## 13. 剩余70项的分批恢复方案

### 13.1 范围、依据与排序理由

本节按管理员要求，将第一阶段完成后剩余70项拆成可分别审计、执行和验收的批次。复用[剩余清单](remaining-missing-after-major-index.json)，不重新执行159项完整性审计。本轮只阅读当前代码和已有JSON证据，未访问DG运行库、Prod或Tushare，未读取Lake行情明细，未启动任何恢复任务，也未修改业务代码。

**以下是批次方案及各批进入前的核验要求，不是所有批次已经完成正式执行准备的结论。** 每批实际来源、行数、读取成本、写入安全和失败续跑仍须核实，落回本节对应批次后，才能按管理员批准范围执行。本轮不提前生成一串可直接运行的命令，避免缺少来源证明或写入范围尚未确定时误启动。

排序作以下细化：

- 先补指数日线、板块基础和普通指数分钟线，分别关闭基础缺口。
- 板块指标与本机ClickHouse同属一条链，放在一个批次内逐步验收，Prod同步另列一批。
- 主要指数日线九转发布只依赖指数日线链，板块Prod发布只依赖本机板块技术指标，不需要等股票年度文件全部恢复。
- 市场成交额只依赖股票分钟Silver和同日股票日线，安排在股票Raw/Silver通过之后；现有job同时生成Gold并写Prod，因此作为包含Prod写入的独立批次。
- 股票前复权、MACD/KDJ及状态、九转分别列批，避免某个年度文件步骤失败后重跑整条股票链。MACD/KDJ与九转均依赖前复权，但两者彼此没有数据依赖；表内先后是默认操作顺序。

该顺序对原阶段8中集中放到末尾的Gold/发布做了细分，目的是让已满足依赖的发布不被股票年度文件工作阻挡；没有改变来源、资产、字段、计算或写入合同。

### 13.2 批次总表

“完成后剩余”以70项原清单按默认顺序扣减，仅表示规划数量；不能提前记成实时审计结果。已完成的主要指数39项不再计入后续批次。

| 后续批次 | 范围与内部顺序 | 项数 | 依赖的后续批次 | Prod写入 | 完成后剩余 |
| --- | --- | ---: | --- | --- | ---: |
| 1 | 指数日线Raw → Silver → 主要指数日线Gold → 日线九转 | 4 | 无需其它后续批次；共享前置另核验 | 否 | 66 |
| 2 | 板块分类Raw/Silver → 成分Raw/Silver → 行情Raw/Silver | 6 | 无需其它后续批次；共享前置另核验 | 否 | 60 |
| 3 | 普通指数Raw五频 → Silver七频 → Gold七频 | 19 | 无需其它后续批次；共享前置另核验 | 否 | 41 |
| 4 | 板块技术指标Gold → 本机CH | 2 | 2 | 否 | 39 |
| 5 | 主要指数日线九转 → Prod PostgreSQL | 1 | 1 | 是 | 38 |
| 6 | 本机板块技术指标 → Prod ClickHouse | 1 | 4 | 是 | 37 |
| 7 | 股票分钟Raw五频 → Silver五频 | 10 | 无需其它后续批次；共享前置另核验 | 否 | 27 |
| 8 | 市场成交额Gold → Prod PostgreSQL（同一job） | 2 | 7 | 是 | 25 |
| 9 | 股票分钟前复权七频 | 7 | 7 | 否 | 18 |
| 10 | 股票分钟MACD/KDJ七频及状态七频 | 14 | 9 | 否 | 4 |
| 11 | 股票分钟前复权九转30/60/90/120分钟 | 4 | 9 | 否 | 0 |
| 合计 | | 70 | | 4项serving目标分布在批次5、6、8 | 0 |

11批逐项映射当前剩余资产，70项各出现一次，无重复、无遗漏。[机器可核验的批次清单](remaining-batches-plan.json)保存每批资产、现有job、依赖、目标位置与检查数量。当前catalog对这些资产共要求136个不同检查目标；这不是已经执行136项检查，也不保证各job实际检查执行次数不会重复。成交额Prod资产目前没有独立catalog blocking check，仍必须验收原生事务读回，不能把“没有独立check”当成免验收。

### 13.3 每批具体安排

#### 后续批次1：指数日线Lake（4项）

现有入口：`raw_index_daily_update_job` → `silver_index_daily_update_job` → `market_major_indices_daily_update_job` → `gold_major_index_daily_nineturn_update_job`。

进入前：Prod当天计数与对象覆盖、日线主要指数名单、21日九转前序及有限上下文；逐项核验现有writer的候选/提升和中断语义。

验收：4项按Raw→Silver→主要指数Gold→日线九转通过各自检查，不发布Prod。 本批当前要求11个不同blocking check目标。

#### 后续批次2：板块分类、成分、行情Raw/Silver（6项）

现有入口：`raw_tushare_dc_index_update_job` → `silver_dc_index_update_job` → `raw_tushare_dc_member_update_job` → `silver_dc_member_update_job` → `raw_tushare_dc_daily_update_job` → `silver_dc_daily_update_job`。

进入前：按当前合同取得source_proof及适用的recovery_identity；核验历史覆盖证明的读取范围，以及需要两轮观察时的300秒间隔；成员必须在同日Raw分类可用后获取。

验收：三条Raw/Silver链6项及各自检查通过；分类、成员与行情按各自真实合同验收，不机械要求彼此代码集合相等。 本批当前要求6个不同blocking check目标。

#### 后续批次3：普通指数分钟线（19项）

现有入口：`raw_index_mins_update_job` → `silver_index_mins_update_job` → `gold_index_mins_update_job`。

进入前：核对silver_index_basic及当前批准的Prod指数分钟对象池；只按22日/五频统计计数和对象覆盖，冻结列投影、导出规模与SQL预算后获取。

验收：Raw5→Silver7→Gold7共19项检查通过；源行数、标准化和派生差异按合同解释。 本批当前要求19个不同blocking check目标。

#### 后续批次4：板块技术指标Gold与本机ClickHouse（2项）

现有入口：`gold_dc_daily_technical_update_job` → `ch_dc_daily_technical_update_job`。

进入前：当前Gold入口读取2024-01-02至22日的Silver历史，先用文件元数据及已批准必要样本测算读取、耗时、内存和重试预算；若涉及全局读取，须另获明确批准后才能读取。

验收：Gold检查通过后才写本机CH；本机同日行数、主键及字段读回通过，不同步Prod。 本批当前要求2个不同blocking check目标。

#### 后续批次5：主要指数日线九转发布到Prod（1项）

现有入口：`prod_core_index_daily_nineturn_sync_job`。

进入前：批次1同日Gold和检查已通过；正式执行前核对Prod目标日现状、精确表和事务边界，执行授权必须包含Prod写入。

验收：只发布core_serving.index_nineturn_daily的22日分区，事务内读回与Gold业务内容一致，通过现有检查。 本批当前要求1个不同blocking check目标。

#### 后续批次6：板块技术指标发布到Prod ClickHouse（1项）

现有入口：`prod_ch_dc_daily_technical_sync_job`。

进入前：批次4本机CH已验收；核对Prod目标日现状和当前同步/替换合同，授权明确包含Prod CH写入。

验收：Prod board_fact_technical_daily同日数据与本机来源对账，保持本机/Prod连接和权限边界。 本批当前要求1个不同blocking check目标。

#### 后续批次7：股票分钟线Raw/Silver（10项）

现有入口：`stock_mins_raw_update_from_prod_job` → `stock_mins_silver_update_job`。

进入前：核验当日Prod完成依据prod_completion_reference、五频覆盖，以及股票基础、身份映射、22日日线和停牌事实；逐频测算明细量及只读导出开销。

验收：5个Raw和5个Silver检查通过。Raw现有目标可复用、缺失目标会读取Prod生成；Silver新建使用write_new，不能套用离线恢复专用的reuse_existing配置。 本批当前要求35个不同blocking check目标。

#### 后续批次8：市场成交额Gold及Prod发布（2项）

现有入口：`gold_wealth_market_turnover_update_job`。

进入前：五频股票Silver与22日股票日线通过；现有job同时选择Gold和Prod发布，不能按只写Lake的任务审批，执行授权须包含core_serving.wealth_market_turnover_snapshot同日写入。

验收：Gold聚合及检查通过后原生job发布Prod；按原合同核对成交额单位、北交所日线校准及JSON内容和目标读回。 本批当前要求1个不同blocking check目标。

#### 后续批次9：股票分钟前复权七频（7项）

现有入口：`stock_mins_qfq_daily_update_job`。

进入前：当天Silver与复权因子覆盖；核清因子修复影响、受影响证券/2026年度文件集合；按已修正写入能力核定候选、继续和最终验收预算。

验收：7项22日记录及检查通过，受影响年度文件中其它日期业务记录保持不变；不能把7项资产当作7个物理文件。 本批当前要求28个不同blocking check目标。

**写入修正已验证，补数未执行：** 目标旁.tmp问题已按专项方案修正，原入口现经staging和逐文件记录，见第14节。不能因此跳过上游及本批正式执行预检，也不增加22日以外历史业务改写授权。

#### 后续批次10：股票分钟MACD/KDJ及状态（14项）

现有入口：`gold_stk_mins_qfq_macd_kdj_daily_update_job`。

进入前：前复权及因子修复检查通过，21日精确前序状态齐备；按已修正写入能力落实逐文件恢复计划和年度读写预算。

验收：7个频率指标与状态成对通过检查；年度指标仅替换22日记录、前序连续性正确，不以从零初始化掩盖缺少前序。 本批当前要求28个不同blocking check目标。

**写入修正已验证，补数未执行：** 年度指标和state均已改用staging并通过故障和真实有界样本验收，见第14节；全市场22日输入、上一交易日状态与成本仍需本批预检，不能按隔离样本直接宣称本批完成。

#### 后续批次11：股票分钟前复权九转（4项）

现有入口：`gold_stk_mins_qfq_nineturn_update_job`。

进入前：30/60/90/120频率QFQ与因子修复检查通过，21日九转及当前算法所需有限历史输入齐备；不直接依赖MACD/KDJ。

验收：4项22日九转和检查通过，历史结果不覆盖。 本批当前要求4个不同blocking check目标。

### 13.4 规模证据与进入执行前必须补齐的预算

复用[21日物理审计](../datasets_recovery_20261021_20261024/dg_dataset_audit_20261021_20261024T022541Z.json)中已有统计，作为量级参考，不重新读取这些文件。它们是21日事实，不能当作22日行数或完整性门槛：

| 范围 | 已有21日参考 | 对分批的影响 |
| --- | --- | --- |
| 指数日线 | Raw/Silver各820行，主要指数Gold与日线九转各11行 | 先完成日线小链；主要日线名单不能照搬分钟前10个代码 |
| 板块基础 | 分类1,043行、成分98,657行、行情1,043行 | 成分取数不能按一次小请求估算；按现行分页/代码范围统计 |
| 普通指数分钟 | Raw 1分钟127,730行，5分钟25,970行 | 与主要指数的3,210行Raw量级不同，不能复用主要指数的50次请求预算 |
| 股票分钟 | Raw 1分钟1,354,376行、约29.3MiB；Silver 1分钟1,341,888行、约20.1MiB | 按五频分别冻结Prod读取量和转换量，避免多次导出当日全市场 |
| 股票年度Gold/指标 | 1分钟当天各1,341,888行，涉及5,568个代码 | 7项QFQ或7项MACD/KDJ是资产数，实际会触及许多股票年度文件；必须按真实受影响文件统计读写量 |
| 板块技术指标 | 目标日1,043行；普通入口从2024-01-02读至目标日 | 目标输出小不代表历史输入小；先测历史文件总量与必要范围，再决定执行方式 |
| 市场成交额 | Gold目标日5行 | 仍须扫描五频股票Silver并做同日日线校准；不能用输出5行推断计算量很小 |

制定第13节时没有执行22日来源计数或新的真实样本；后续已增加第14节的Raw计数和股票真实有界样本，其余各批源规模及成本仍未冻结。不能按21日参考值直接设22日应有行数。每批进入正式执行前，必须补齐：

1. **对象和范围**：22日应有对象、五频或七频范围、相关日期、共享基础资产、目标文件/表，以及文件存在冲突；年度资产另列受影响股票、年份和实际文件数。
2. **读取和计算预算**：源端字段投影、当天计数及覆盖、连接/SQL/分页次数、读入行数/字节、DuckDB扫描/聚合/排序、峰值内存、spill及临时目录。优先复用来源明确且仍适用的已有证据，仅补缺少的有界核验。
3. **输出和恢复预算**：预计文件/行数、候选和正式占用、逐文件持久化依据、请求/写入重试上限、取消检查点、失败后继续及最后验收的成本。正常耗时、最长允许耗时与告警/停止行为分别写明。
4. **不能接受的情况**：来源未就绪、范围/字段不符、候选路径不合规、已有文件将被未授权覆盖、历史因子修复范围外溢、读写量或耗时超预算，均停止该批，不靠放宽检查、换源、安装扩展或临时脚本绕过。

本节不编造固定分钟数或磁盘预算来代替测量。板块来源证明若要求两轮稳定观察，当前间隔为300秒，应计入总耗时；不照搬资金流的60秒。普通指数和股票Prod导出还应确认现有DuckDB PostgreSQL扩展已安装可用，禁止运行时自动安装或下载。

### 13.5 年度写入问题的修正前依据与当前处理

以下保留修正前审计依据，当前代码已经按第14节完成修正：

- `defs/assets/stk_mins.py::write_gold_stk_mins_qfq_asset_partition` → `defs/stk_mins_qfq.py::write_gold_stk_mins_qfq_rows_to_year_files` → `_write_gold_qfq_group_to_year_file`。后者通过`_temp_path_for`在正式目标旁生成`part-000.parquet.tmp`，然后替换年度目标。
- `defs/assets/stk_mins_qfq_macd_kdj.py` → `defs/stk_mins_qfq_macd_kdj.py::write_gold_stk_mins_qfq_macd_kdj_asset_partition`及年度指标writer。修正前`_temp_path_for`在正式目标旁生成`.part-000.parquet.tmp`，state也使用同一函数。

修正前这些调用属于现行入口，确实不满足候选必须放staging的规则。随后管理员明确授权修正，已先落[方案和LLD](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md)再开发，旧临时路径已移除，隔离回归及真实只读样本核对通过。**批次9和10的这项代码前提已处理，正式补齐尚未执行。** 其它前提、年度读写范围和预算仍按各批核验，不得直接跳到全市场运行。

股票前复权缺的是22日记录，不是整年数据不存在。年度文件整体可能需要重写，文件hash和mtime会合法变化，验收应对受影响文件确认非22日业务记录未改变；不能把日分区“相邻日期文件stat不变”的办法机械套到年度文件。需要的差集/业务hash、读取范围与开销必须事先列入该批预算，只针对受影响股票/频率/年份，不能扩成全库全历史审计。

因子修复若要求改变22日以外的历史业务结果，属于额外范围，先列清受影响对象/日期、原因、代码和预算再确认；不自动全历史重算。其它批次的现有writer也须在进入执行前核对，本文没有宣称它们已经全部满足候选、checkpoint和中断要求。

### 13.6 逐批推进、失败与最终验收规则

- 所有批次只以22日缺口为业务目标；已恢复主要指数39项、已有ETF与资金流不重采、不重写。共享快照、对象池、身份映射或交易日历若不满足要求，先说明问题，不顺手更新它们。
- 获准执行的批次按内部job顺序推进，检查通过后才进入下一步；一个或多个批次已获明确授权时，不因为人为分批重复索取相同授权。制定第13节时仅获准方案；随后管理员已授权先修正两条股票写入链再补齐，当前实际进展和冲突停点见第14节，不把新发现的额外代码修正和Prod补源写入自动纳入原范围。
- 失败只阻断其真实下游。独立批次在各自准备条件与执行授权满足后可以单独推进，不把表格操作顺序伪装成数据依赖；例如股票年度写入问题不会使已就绪的日线九转发布变成技术上不可做。
- 不统一宣称所有job均可安全重跑。先读本次run、已发布文件、现有checkpoint或逐文件事实，区分已成功、缺文件、检查失败及部分发布；有文件而检查失败不得覆盖或补runless绿事件，未授权不删数据、不清理现场、不重跑整条链。
- 本地CH和Prod CH分开验收；PostgreSQL事务发布与ClickHouse当前同步合同分别核对，不能互相套用原子性保证。批次5、6、8的授权须明确包括各自Prod目标和22日范围，禁止无日期限制的清空或替换。
- 每批完成只读该批run的有界物化/check记录与当前目标文件或同日serving计数，复用原生已通过的完整检查。公式不重复算，年度大文件不在每一步重新全量比对；必要的目标/来源对账只按已预算范围执行一次。
- 每批在本文追加预检、配置来源、完整实际命令、run_id、读写数量、耗时、检查与失败处理，然后从70项清单扣除真实验收通过的资产。最后仅对本次恢复范围汇总一次，不再重跑159项全局审计。

### 13.7 本轮方案交付与下一批

本轮只新增[11批资产与依赖清单](remaining-batches-plan.json)并更新本文；已在本地核对70项集合完全相等且各出现一次，默认顺序满足依赖。CodeGraph与当前job、asset、配置构造器和writer已用于核对分批依据；没有把命名或旧文档当作执行事实。

建议下一步先对**后续批次1：指数日线Lake4项**做必要审计：复用21日820行的已有统计作为规模参考，仅补22日真实计数与对象覆盖、21日前序、当前文件/物化状态，以及现有writer的候选和失败语义。不能假定22日也必须为820行；完成该批具体方案、预算和确认后再执行。其它10批按表逐批准备，不提前读取所有来源明细。

截至本节更新，没有启动后续job、sensor、backfill、runless事件或新的来源请求，没有修改业务代码或Prod/Lake数据。主要指数第一阶段的成功记录保持不变。

## 14. 两条股票写入修正结果与补齐预检停点

本节是后续执行当前事实，第13.7节保留当时只制定分批方案的历史记录。

### 14.1 先落方案，再修改两条股票写入链

管理员已授权“先修复这两条，然后再进行数据的补齐”。对应[方案和LLD](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md)在编码前完成，原股票分钟设计、QFQ治理LLD和MACD/KDJ方案均已同步。

改动限定于QFQ、MACD/KDJ年度及state写入：

- 候选、冻结输入、逐文件完成记录和锁均在staging；本次调用全部候选校验后再逐文件同设备替换，不声称全批一起原子提交。
- 同一根run可在输入相同、候选与目标吻合时继续；真实进程退出在替换与完成记录之间也能核对后继续。输入改变、外部改目标、候选损坏、跨设备或并发writer会拒绝。
- 不删除失败候选，不改公式/因子日期/字段/频率/检查/job/正式目标布局。QFQ因子repair与history、MACD repair/history和BSE候选共用原writer，不另开计算入口。

实际验证：

| 验证 | 结果和范围 |
| --- | --- |
| 15个相关隔离测试文件 | 263 passed、70 subtests passed，21.97秒；含两类金样本、年度合并、repair/history/derived/BSE和静态门禁；[日志](qfq-staging-code-tests.log) |
| 真实只读样本与隔离写出 | `600000.SH`60分钟20/21日14行有界事实，schema符合；QFQ保留/新增记录一致，MACD和state与已有正式21日结果最大差均0；重复执行不改隔离输出inode/mtime，0.140秒；[报告](qfq-staging-real-sample-verified.json)、[脚本](qfq-staging-real-sample.py.txt)、[日志](qfq-staging-real-sample.log) |
| 静态检查 | 新增文件、两个核心writer和新增测试默认Ruff通过，全项目致命基线通过，diff与文档完整性通过；两个asset文件原有7/2项默认Ruff问题与HEAD一致，未新增或顺手修改 |
| 正式资源边界 | 样本只读4个正式来源文件共577,907字节，stat未变化；写出仅在`/private/tmp`，无正式物化、事件或数据修改 |

本次CodeGraph使用explore、两个impact、修改后sync/status，覆盖入口、共用writer、repair/history调用方、checks和下游；没有Web/API或跨子系统合同改动。真实样本只证明字段衔接、结果保持与幂等，不代表22日全市场已验收。完整测试命令及约束对账见专项LLD第8节。

### 14.2 第1批的必要预检：未通过，不启动任务

执行只读命令（工作目录`lake_console/orchestrator`）：

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python -B /private/tmp/dg_20261022_index_daily_preflight.py
```

[预检脚本](index-daily-raw-preflight.py.txt)、[结果](index-daily-raw-preflight.json)：

1. 本批4个目标文件及22日物化均缺失；4个相关job无活动run，daemon未运行，22日分区已登记。Lake与staging同设备、可访问、空间充足，现有Postgres扩展已安装，不需要也没有安装。
2. 当前DG已登记指数820个，代码集合hash为`1129cb88459d4bc7235f78fac8d08c62`。只读Prod `core_serving.index_daily_serving`，按`trade_date=2026-10-22 AND ts_code=ANY(已登记集合)`计数，**0行、0个代码，缺820个**。最多5个缺失样本为`000001.SH/000002.SH/000003.SH/000004.SH/000005.SH`。不将21日820行参考误当作22日真实源事实。
3. 实际使用2次Prod只读事务连接，共3条业务SQL（计数2次、最多5个缺失样本1次；另各1次SHOW核实只读）。首次审计脚本字段名问题已纠正，覆盖失败后补存失败证据；没有明细导出、全历史扫描或全局数据集审计，没有用DagsterInstance初始化/写入。
4. 当前Raw入口本来就要求已登记代码完整返回；0行会被拒绝。本轮不更换到Tushare、不改变对象池、不放宽检查，也未生成可执行Raw配置或启动job。

### 14.3 另两处日线写入问题与后续处理建议

进入第1批时按方案核对真实writer，确认：

| 本批步骤 | 当前实际写入代码 | 发现的问题 |
| --- | --- | --- |
| 指数日线Silver | `defs/assets/index_daily.py::write_silver_index_daily_partition_from_raw_file` → `_replace_parquet_from_query` | 在正式目标旁生成`part-000.parquet.tmp`，有同名文件先删除 |
| 主要指数日线Gold | `defs/assets/market_major_indices.py::write_gold_market_major_indices_daily_partition` → `_replace_parquet_from_query` | 同样在正式目标旁生成固定名称.tmp |

这是另两条日线写入实现，不是本次股票QFQ/MACD修改回退或修改失败。当前没有改它们，也没有执行它们。原批次1“可直接执行”的准备条件尚不成立，不能因管理员要求补齐而绕过已发现的问题。

建议下一步顺序：

1. 对Prod22日指数日线来源做限定范围的原因追查，核对现行同步入口、源数据与该日结果；先给出Prod补源的精确方案与读写预算，不由DG换源或擅自运行Prod同步。
2. 将上表两个日线writer作为另一个明确修正范围，先完成原方案/LLD、全部调用方影响面和单日文件失败/继续设计，经确认后修改；不把QFQ专用实现扩成任意数据集框架，不顺手迁移周线、月线或其它资产。
3. 两项前提通过后，才按原批次1的Raw→Silver→主要指数Gold→日线九转逐步执行，各步检查通过再继续，随后按第13节推进后续批次。只补所缺当前事实，不再次扫描159项。

依据[根AGENTS第158行](../../../AGENTS.md#按计划开发执行链)“若发现计划口径与当前实现、真实数据或源接口行为冲突，必须停下来说明冲突点，等待确认”，本轮停在这些新增问题前，未扩大代码或Prod写入范围。独立批次不因本批而技术上全部阻断，但本轮没有跳过本批去提前启动其它未预检批次。

### 14.4 本轮结果

两条股票写入修正及其测试、真实样本验收完成；正式补齐未启动，原主要指数39项成功事实保持不变。剩余缺口仍沿用原审计扣除已恢复39项后的70项，没有新增验收通过项可扣除；这是集合进度，不是再次全局审计的结果。没有提交Git、修改sensor/daemon/cursor/动态分区、运行Kopia或安装依赖。


## 15. Prod更新后复核与两处日线写入修正

### 15.1 授权及Prod计数覆盖

管理员已明确要求：核对22日Prod指数日线；先将Silver及主要指数日线Gold的方案/LLD落文档，再修复和验证，随后逐批补齐，不重复全局审计。本节接续第14节，原Prod0行报告保留为当时事实。

[新预检](index-daily-raw-preflight-after-prod-update.json)确认：`core_serving.index_daily_serving`在22日、DG登记820代码范围820行/820代码，缺失0、重复0，代码集合hash为`1129cb88459d4bc7235f78fac8d08c62`。只执行1条业务聚合SQL，未导出Prod明细；事务只读。相关4个job无活动run，4个目标文件及同日物化仍缺失；分区已注册，daemon未运行，Lake与staging同设备，PostgreSQL扩展已存在。预检脚本归档为[index-daily-raw-preflight-after-prod-update.py.txt](index-daily-raw-preflight-after-prod-update.py.txt)，Raw原生配置已保存为[index-daily-raw-run-config.json](index-daily-raw-run-config.json)，尚未执行。

实际预检命令（在`lake_console/orchestrator`，使用本机授权网络权限）：

```sh
.venv/bin/python -B /private/tmp/dg_20261022_index_daily_preflight.py
```

### 15.2 两处日线写入已修复和验证

编码前已建立[方案和LLD](../../docs/design/dagster-index-daily-staging-write-plan-and-low-level-design.md)，原指数日线方案/LLD与主要指数方案/LLD已同步引用。改动为新单文件写入模块、Silver writer、Gold writer及其日常入口；候选/锁/记录位于外部staging，同设备替换，可核对中断现场后继续；保留原去重、日期、seed、公式、检查及入口。

- [14个相关测试文件](index-daily-staging-code-tests.log)：241 passed、14 subtests passed，9.55秒。含替换前后异常、真实子进程退出、冲突拒绝和幂等继续，未跳过或放宽原测试。
- [真实21日样本核对](index-daily-staging-real-sample-verified.json)：仅3个文件、123,257字节；Silver820/Gold11行，schema一致、双向差集0，重复执行不重写，来源stat不变，正式写入0，耗时0.285秒；[脚本](index-daily-staging-real-sample.py.txt)。
- 改动文件默认Ruff、项目致命错误基线、文档完整性及diff检查通过；CodeGraph同步结果另行补充。

上述是真实输入的隔离验证，不算22日正式恢复。没有重扫159项，也没有再次执行已恢复39项或ETF/资金流任务。

### 15.3 执行前查到Raw候选目录冲突

`defs/paths.py::raw_index_daily_staging_path`返回正式根下的`raw/index_daily/_staging`，Raw原生writer确实使用此路径；底层还会删除同名旧候选，随后直接替换正式目标。此前未追到最终路径，漏查了这处，并非Prod本次更新导致。当前测试也把Lake内旧路径作为正确预期，不能据此判断现行目录规则已经满足。

根AGENTS要求候选只写`/Volumes/datasource/data_lake_staging`；本步方案又明确只改Silver/Gold，因此这是额外代码范围，不能静默扩入或换临时入口绕过。具体证据和建议范围已写入[专项文档第9节](../../docs/design/dagster-index-daily-staging-write-plan-and-low-level-design.md#9-执行前新发现raw候选目录冲突待确认额外范围)。建议确认后只修Raw指数日线候选、失败留存和单文件继续依据，先补其LLD和测试，再接回第1批4个原生job。

截至本节，后续正式run启动0、额外恢复资产0、剩余仍70项。已完成两个日线writer的代码和验证；第1批暂停在新增Raw范围确认前，不代表其它独立批次在技术上都依赖它。未提交Git，未修改sensor/daemon/cursor，未运行Kopia、安装依赖或写Prod/Lake正式数据。


### 15.4 Raw额外范围已确认并先补方案

管理员已确认纳入Raw修正并要求验证后继续。具体LLD已先落[专项文档第10节](../../docs/design/dagster-index-daily-staging-write-plan-and-low-level-design.md#10-raw额外修正方案与lld开发前)，原指数日线方案和LLD已同步；随后按其范围开发，不再请求相同授权。


### 15.5 Raw额外修正验证通过

[最终回归](index-daily-raw-silver-gold-staging-code-tests.log)248项测试、14项子测试通过；[Raw真实隔离核对](index-daily-raw-staging-real-sample-verified.json)21日820行/820代码、schema一致、双向业务差集0、幂等不重写，正式写入0。两个日线writer的原验证继续适用；CodeGraph已sync/status，无pending；默认/致命Ruff及文档检查通过。Raw目录、失败留存和中断继续问题已处理，可以进入第1批正式恢复。

## 16. 后续批次1：指数日线Lake4项执行计划

本节在正式执行前建立，执行授权为管理员本轮“通过后继续逐批补齐”及Raw范围确认。工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，正式`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`。使用已安装`.venv/bin/dg`，已读`dg launch --help`和本地launch实现，运行现行原生job；不使用uv、不安装、不启停服务或sensor、不注册分区。4个目标当前均不存在。

### 16.1 输入、预算、边界

[新鲜执行预检](index-daily-batch1-execution-preflight.json)只读相关instance状态和文件元数据，未重复Prod SQL。Prod计数覆盖复用第15.1节；原生Raw任务会按原合同只读22日820代码/11列，输出820行。Silver读新Raw一份并输出820行；Gold读新Silver一份、seed11行，输出11行；九转读最多20个Gold日文件及21日九转前序，既有输入51,243字节，连新文件预算256KiB，输出11行。前后保存8个21/23相邻日期路径stat。

本批总候选/日志/receipt预算64MiB，现有空间充足且同设备；常驻内存沿用DuckDB资源配置，不在Python加载明细。预计含CLI加载2～5分钟，10分钟无进展先检查不盲重跑。4资产、11个blocking check；不是全局扫描。

### 16.2 正式命令和逐步验收

按以下次序，**每条命令成功且该run预期checks全部通过后**才执行下一条；日志分别保存于本目录。CLI的配置选项以当前help为准为`--config`。

```sh
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job raw_index_daily_update_job --partition 2026-10-22 --config ../reports/datasets_recovery_20261022_20261024/index-daily-raw-run-config.json
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job silver_index_daily_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job market_major_indices_daily_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_major_index_daily_nineturn_update_job --partition 2026-10-22
```

Raw2、Silver4、Gold4、九转1个checks；逐run读当前有界事件验收，失败只停该链后续。最终一次合并读回4个目标schema、目标日/行数及代码覆盖，并检查8个邻日stat不变。通过后只从已有70项清单扣这4项到66，不再次扫描159项。

### 16.3 中断/失败处理

Raw/Silver/Gold按新receipt逐文件核对；同根run可接着执行，输入或目标变更拒绝，失败候选保留。Raw继续会按LLD重读同日来源并核对内容摘要，不能只比行数。九转使用现行独立候选、校验后单文件替换；若run失败，先查本run事件与目标文件，不自动整链重采、有文件不直接覆盖，不运行runless补绿。未获授权不清理现场或已成功目标。每个job先记录run_id、终态和checks再推进。

### 16.4 实际结果

第1批已完成：4个原生job均SUCCESS，Raw820行、Silver820行、主要指数Gold11行、日线九转11行；11项blocking检查全部通过。

| job | run_id | 结果 | Dagster运行耗时 |
| --- | --- | --- | --- |
| raw_index_daily_update_job | `dad9c21f-00dd-49ab-bb19-fd68e268e499` | SUCCESS | 5.76秒 |
| silver_index_daily_update_job | `d19d59a7-51ac-4103-ad3c-6ecad2c40d98` | SUCCESS | 6.07秒 |
| market_major_indices_daily_update_job | `56d6ecc1-2910-4180-9c0b-d4a256412d58` | SUCCESS | 5.94秒 |
| gold_major_index_daily_nineturn_update_job | `c4abbc90-5899-4fd2-992a-52058c3868f6` | SUCCESS | 5.24秒 |

[最终物理验收](batch1-index-daily-final-verified.json)一次读回4文件，schema、当日行数/代码数通过；8个邻日路径及九转历史输入stat不变。每job详细检查见相应`*-verified.json`，日志见`batch1-*.log`；[只读验收脚本](index-daily-readback.py.txt)。本批实际4项从70扣到66，未重复全局审计。


## 17. 后续批次2、3、4、6、7的必要预检和停点

- 批次2：[22日Prod板块计数](batch2-dc-source-counts.json)，3条计数SQL确认`core_serving.dc_index`、`core_serving.dc_member`、`core_serving.dc_daily`各0行，6个目标仍缺。现行`observe_dc_board_source`先要求Prod完成依据，空来源无法取得proof；不请求Tushare整日、不运行必败job，不改现行来源合同。其下游批次4、6也暂不满足上游条件。需要管理员先补Prod22日这3个数据集，随后只复核该日计数和来源证明。
- 批次3：CodeGraph及当前`assets/index_mins.py::write_raw_index_mins_partition_from_prod_db`确认Raw把`.p2-<uuid>.tmp`写在正式目标旁；`assets/index_mins_silver.py::_stage_and_promote`对Silver使用目标旁`.p3-<uuid>.tmp`。这两条都不满足外部staging要求，不能按现状启动；Gold已有外部staging，不因此修改它。当前只读代码审计，未读取普通指数分钟大表或修改此链代码。
- 批次7：进入下一独立链前静态检查`assets/stk_mins.py`，Prod Raw底层`_write_raw_stk_mins_rows_from_prod_db_source`及Silver的最终写出仍使用目标旁`.tmp`，分别在约936、2046行生成。该组同样需另纳入代码修正，未开展全市场读取或启动股票分钟job；此前已修的QFQ/MACD是下游年度writer，不能覆盖这里的Raw/Silver。批次8～11暂不能越过缺失的股票Silver/QFQ来源。

上述新增代码问题须按根AGENTS冲突规则确认范围后，先补原方案/LLD、影响面、逐文件继续和有界验收，再改代码；不扩大成全仓writer重构。当前已确认日线修正范围不自动覆盖这些分钟线writer。独立且来源已通过的批次5可以先发布，不因上述停点全部停工。

## 18. 后续批次5：主要指数日线九转Prod发布方案与执行细节

本节在执行前建立，沿用管理员“验证后继续逐批补齐”的授权，范围只含`prod_core_index_daily_nineturn`在2026-10-22的11行。批次1已验收，所以该发布仅依赖已完成来源；批次2、3的停点不影响它。无代码、配置、schema或合同变更。

### 18.1 代码、目标和预算

CodeGraph核对资产`index_daily_nineturn_prod_core.py`→`prod_db/index_daily_nineturn.py::replace_prod_core_index_daily_nineturn_partition`→正式blocking check。读取22日日线Gold和九转Gold各11行，复用本批物理验收；原loader仍作发布前合同检查。通过现行`ProdPostgresWriteResource`写`core_serving.index_nineturn_daily`，只针对22日，当前0行、无物化及相关活动run，现行9列schema匹配。[预检证据](batch5-index-nineturn-prod-preflight.json)。

普通Prod只读账号最初被该表权限拒绝；查明正式check使用本来就有的`ProdPostgresWriteResource.connect_readonly()`后，复用这个只读方法完成预检，未改权限或数据。21日11行、23日0行作为邻日计数保留；不读全历史。

写入按原事务：仅删除22日行（本次0行）→插入11行，单页上限100→事务内同日读回并比业务hash→提交；原check再按22日对账。预计几秒，CLI启动预算2分钟；内存11行、SQL至多数条，staging/Lake写入0，候选和备份均不新增，日志小于8MiB。失败事务rollback；提交后若事件失败，先读回11行及hash再决定续跑，不把run失败当作未提交，不自动覆盖或重跑整批。单个11行事务预期远小于60秒，不属于Prod长批计算。

### 18.2 命令与验收

工作目录同第16节，正式DAGSTER_HOME不变；以下只执行1次，不重新跑批次1。

```sh
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job prod_core_index_daily_nineturn_sync_job --partition 2026-10-22
```

保存run_id和日志；SUCCESS、1物化、1 blocking check必须对应当前22日；复用原生事务读回/check hash，最后只读一次同日计数/主键覆盖及21/23日计数。完成后从66扣1到65，其它阻塞批次不扣除。

### 18.3 实际结果

Prod发布已完成，run_id=`c0642486-dfd3-4a91-b939-c1f0311df307`，SUCCESS，Dagster执行5.83秒。22日11行/11代码，事务内读回及正式blocking对账check通过，Gold期望业务hash与Prod实读一致；21日仍11行、23日仍0行。见[验收结果](batch5-index-nineturn-prod-verified.json)、[任务日志](batch5-index-nineturn-prod-sync.log)和[只读核验脚本](batch5-index-nineturn-prod-readback.py.txt)。未重跑批次1，未修改Lake。验收脚本初次读取metadata漏了现行`goldenshare/`前缀，修正脚本后仅重新查询本run事件，不重新执行发布。


## 19. 本轮累计结果与下一步

- 日线代码：先方案/LLD后修改Silver和主要指数Gold；执行前另发现Raw候选目录冲突，经管理员确认后补LLD并修正。最终248项测试、14项子测试通过，两份真实21日隔离核对通过，Raw/Silver/Gold合同及原业务值保持；无新资产/字段/参数/配置，无跨工程变更。
- 正式恢复：后续批次1的4项与批次5的1项完成，5个原生run均SUCCESS，12个blocking checks通过；4个Lake新文件与Prod同日11行读回通过。邻日/九转历史未变，未再次做全局审计。原109缺口累计恢复44项（先前39+本轮5），当前尚缺65项；这是已有集合扣减，不宣称其它数据集质量已重新审计。
- 板块：待管理员补Prod22日`core_serving.dc_index`、`core_serving.dc_member`、`core_serving.dc_daily`（各0行）。仅以3条计数查询确认，不把未请求Tushare的来源记成Tushare缺数。批次2及依赖它的4、6暂不能推进。
- 分钟代码：新增范围确认已向管理员提出，具体为普通指数Raw/Silver和股票分钟Prod Raw/Silver四处正式目录旁候选；未擅自修改。普通指数19项和股票后续链因各自代码/上游条件暂停，已完成日线不受影响。

没有新增全局数据读取、启停sensor/daemon、修改cursor/分区、运行Kopia、安装依赖或Git提交。后续范围确认后先落相应原方案/LLD、影响面和预算，再修复验证、恢复原批次；不绕过现有检查或切换来源。


## 20. 四处分钟写入修正授权及开工前方案

管理员已确认“纳入四处修正，按批次继续”。具体硬口径、影响面、实现位置、配置/读写边界、单文件中断继续、性能/最后验收成本与正反测试已先写入[专项方案和LLD](../../docs/design/dagster-minute-raw-silver-staging-write-plan-and-low-level-design.md)，普通指数原方案/LLD及股票原设计/导出方案已同步。当前65项缺口不因开发扣减；板块仍待Prod补源。


## 21. 普通指数分钟批次3：必要来源计数预检

四处修正已获准；开发验证进行中，此时仅做22日来源计数。按AGENTS.local使用`bash scripts/psql-remote.sh`及既有`.env.web.local`连接；READ ONLY事务、30秒SQL超时。白名单为`ops.index_series_active`的resource/ts_code（resource=index_mins范围计数）及`raw_tushare.index_mins`的freq/ts_code/trade_time聚合；过滤22日、五频、当前对象池，返回1条JSON汇总/最多5个频率计数，明细导出0、业务写入0。复用21日约530代码/170130行参考测算，不重复全局审计；报告保存`batch3-index-mins-source-counts.txt`。代码与隔离/真实样本验收通过后才补正式执行计划及预算。


### 21.1 普通指数来源计数结果及股票下一步

当前Prod普通指数对象池530条且唯一；22日五频聚合无记录（0行），已保存报告，不执行必败普通指数job。接着只核对`raw_tushare.stk_mins`同日五频freq/ts_code/trade_time统计，仍用remote脚本、READ ONLY、30秒超时，返回最多5行汇总、明细导出0；报告保存`batch7-stk-mins-source-counts.txt`。如果为0则不查TaskRun或全市场对象池；如有数据，再按正式完成reference合同核验，不凭计数启动Raw。


## 22. 四处分钟写入修正结果与最新恢复停点

### 22.1 已完成的代码与验证

本轮按第20节先落方案/LLD并同步4份原设计，再修正四处writer。新模块限定普通指数与股票Raw/Silver，候选/锁/receipt移到正式staging；保留原业务SQL、字段和入口，坏候选不会提升，失败现场保留，同文件同设备替换；中断后复用已验证候选或读回已完成文件，避免整天分钟数据反复导出。股票历史/BSE专项候选输出及frozen行范围保留。

- [311项测试、21项子测试汇总](minute-staging-validation-summary.json)：128普通隔离案例、183现有OS隔离案例，18个不同文件，未累计重复运行。原Raw/Silver、派生、校准、历史/replace、BSE/frozen、job及113项静态门禁全部通过。
- [真实21日有界样本](minute-staging-real-sample-verified.json)：两族各2代码、四个输出各10行，schema一致、双向业务差集0、幂等不改文件；8个来源stat不变，正式写入0、Prod连接0，0.369秒；[脚本](minute-staging-real-sample.py.txt)。
- definitions在独立临时DAGSTER_HOME加载通过，禁止依赖同步/下载；全项目致命Ruff、diff和文档检查通过。新模块及测试默认Ruff通过；旧文件10项既有默认Ruff问题已与HEAD逐项核对，无新增，见[基线](minute-staging-ruff-baseline.json)。完整硬口径/测试对账、入口纠错及剩余边界见[LLD第7节](../../docs/design/dagster-minute-raw-silver-staging-write-plan-and-low-level-design.md#7-实施和执行记录)。

### 22.2 新的必要计数结果：两个分钟来源都没有22日数据

[计数汇总](minute-prod-source-counts-verified.json)及原始[普通指数](batch3-index-mins-source-counts.txt)/[股票](batch7-stk-mins-source-counts.txt)报告确认：

| Prod目标 | 22日计数结论 | 需要补源的范围 |
| --- | --- | --- |
| `raw_tushare.index_mins` | 五频均0行；当前对象池530条且唯一 | 1/5/15/30/60分钟、22日完整对象池 |
| `raw_tushare.stk_mins` | 五频均0行 | 1/5/15/30/60分钟、22日全市场，并完成现行TaskRun完成依据 |
| `core_serving.dc_index` / `dc_member` / `dc_daily` | 复用第17节各0行的计数证据 | 22日板块分类、成分及行情；本轮不重复查这三表 |

两个新查询经现行remote脚本、READ ONLY事务和30秒超时，各仅1条当天五频聚合SQL，返回至多5组计数；明细导出0，未做全局审计。已本地核对remote脚本与DG resource的host/port/database一致，只保存相等布尔值，不输出凭证。各报告记录完成时间，结论只代表该次计数时点。

### 22.3 当前缺口与后续顺序

当前65项仍由原缺口集合减去已恢复44项得到，没有重扫159项。四处代码问题已处理，已无需重复确认修正范围；本轮未启动新的正式补数任务，不能把隔离样本记成22日补齐。

- 板块来源先补齐，之后批次2的6项→批次4的技术指标/本机CH→批次6的Prod CH；历史计算读取仍需进入该批时按规则评估，不因代码修复获得全局明细读取批准。
- 普通指数五频补齐后执行批次3的Raw5→Silver7→Gold7，共19项。
- 股票五频全市场源和完成依据就绪后执行批次7的Raw/Silver10项，再按批次8成交额、9 QFQ、10 MACD/KDJ、11九转推进。各步先核对真实输入和预算，不重复读取大范围数据。

板块/普通指数/股票为三条独立来源，不要求全部补好才推进已就绪链。现行源和完整性检查不放宽；累计已恢复的44项不重跑。没有安装依赖、修改Prod业务代码/数据、修改正式instance/sensor/cursor、运行Kopia或提交Git。

## 23. 2026-10-25 Prod补齐后继续：只做原缺口的必要核验

管理员已明确“Prod刚完成一轮补齐，审计后继续DG补齐”。本轮仍只处理2026-10-22剩余65项，不扩展到23日，不重新扫描目录159项，不改业务代码或部署Prod。正式执行授权沿用原批准批次及本轮继续指令；按批次成功检查后推进。

### 23.1 来源计数和执行前代码审计

只读复用原五频SQL和板块三条同日计数，经psql-remote脚本执行：板块dc_index1043/1043唯一键、dc_member98530/98530、dc_daily1043/1043；普通指数对象池530且唯一，五频全部530代码、总170130行，主键计数均等于行数；股票五频5577代码，行数分别1354617/275385/95513/50545/28237，重复主键0。见`resume_20261025/prod-*-counts.txt`。这些计数不代替来源proof和原生资产检查。

代码审计确认普通指数19项可用原生3个job；板块6项有原生source_proof入口；股票10项仍需现行Prod完成依据。原native/derived与check语义不改。只读预检未创建DagsterInstance：35个目标均不存在，相关job无活动run，daemon未运行，Lake和staging同设备、可读写、空闲约2.65TiB。DuckDB仅LOAD postgres成功，未INSTALL；证据`resume_20261025/preflight.json`。

股票gate当前返回prod_ops_task_run_missing：预期当前listed+CNY且截至22日5576代码，不能以5577源代码总数冒充门禁通过；需查明本次维护时间输入。预检中误用了不存在的cn_a_stk_mins_trade_days名称，不能将该false当作分区缺失；正式股票执行前应核对当前实现的cn_a_stock_mins_trade_days及cn_a_stock_mins_silver_trade_days。没有注册或修改分区。

### 23.2 批次3普通指数19项：方案、LLD和正式执行卡

目标：Raw5→Silver7→Gold7，均仅22日新文件及原生物化/check。Prod字段投影沿当前Raw11列；范围为22日、1/5/15/30/60和resource=index_mins当前530代码池。五频预计分别127730/25970/9010/4770/2650行；Raw总170130行。Silver原生五频及90/120派生、Gold竞价锚点转换按既有合同验收，不要求三层行数机械相等，也不宣称原Raw已验证固定全日网格。

实现位置与影响面：`assets/index_mins.py`、`index_mins_silver.py`、`index_mins_raw.py`、`index_mins_silver_defs.py`、Gold现行入口；沿用分钟writer专项LLD，不改代码/配置/源参数/active pool/Basic。Raw/Silver候选与receipt位于正式外部staging，同设备原子提升；Gold也是外部候选，但无分钟receipt，目标已存在拒绝。

预算：5次同日Prod导出，170130行；Silver/Gold只读同日输入，无跨日历史明细。3个job、19文件/19检查；候选/记录/日志256MiB，预计3—10分钟，10分钟无进展先查本run，不盲重跑。已有21/23邻日38个路径stat记录，不读其内容。最后仅取3run/19check和一次19文件schema/同日聚合及邻日stat；中断检查预算同一run最多300事件，不能重扫全目录。

工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，DAGSTER_HOME=`/Users/congming/.goldenshare/dagster_home`，既有`.venv/bin/dg`；本地help和当前官方CLI文档已核对，不运行uv或安装。分区cn_a_index_mins_trade_days已注册。完整命令按下列次序，一条SUCCESS且相应checks通过后才继续：

```sh
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job raw_index_mins_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job silver_index_mins_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_index_mins_update_job --partition 2026-10-22
```

失败/中断：先保存run_id和本run失败事件，只停该链后续。Raw/Silver已成功正式文件可按原合同验证复用；validated候选只承诺同root_run_id继续，新独立launch不可宣称能复用旧root未提升候选。Gold若部分成功，不可盲重跑整job；按实际缺失资产复核后另落精确继续步骤，不覆盖已有文件、不runless补绿。原Gold失败清理本run候选，不能声称留存可续候选；失败日志和已成功文件保留。验收通过才从65扣19，既有44项不重跑。

## 24. 板块批次2：方案、LLD和执行约束（2026-10-25）

目标为22日分类、成员、行情Raw/Silver六项；现有Prod分别1043/98530/1043行。只运行原生job，不改代码或配置合同。顺序Raw index→Silver index→Raw member→Silver member→Raw daily→Silver daily；成员先依赖同日Raw分类。

来源依据沿用`asset_guards/dc_board_source_probe.py`和`dc_board_source_freeze.py`。先用现行Prod reference与Tushare同日index/daily完整快照检查身份一致性；最多16请求/轮，不读历史。若index−daily非空，本轮先记录缺口，不调用history coverage，等明确历史读取批准；没有差集时原coverage入口直接返回空证明，无历史SQL。用`confirm_dc_board_source`分别冻结三个Raw目标proof，再由`build_raw_dc_board_update_job_run_config`生成source_proof+recovery_identity=None的正式配置，不手造自动任务身份。过去日且内容与Prod相符可一次观察确认；否则严格等待300秒并再观察，离线确认总限600秒，不放宽稳定要求。

写入位置是现行`assets/dc_board.py`、`dc_board_silver.py`及`io/dc_board_candidate.py`：候选在正式外部staging/run_id下，同设备校验后替换单目标文件。每job仅一个目标、一个blocking check；6目标缺失且无活动writer，21/23邻日stat已保存。旧板块writer失败可能清理本run候选，没有分钟receipt能力；失败保留DG事件/日志，先核对正式目标再决定精确重跑，不声称可复用已清理候选、不覆盖已有成功目标。

Raw index/daily来源快照各约1043行；member从1043板块逐码分页，每页5000，沿原限流0.13秒/请求、最多1200请求、600秒。预估约1043次主请求加必要末页/重试，实际仍受1200上限；若源数量/请求预算超限，原实现拒绝，不扩大配额。正式读取、归一化与写入以现行schema、主键、类别和proof校验为准，不强行令成员行数等于Prod计数。Silver仅同日对应Raw。候选/记录/日志预算128MiB，整批预算15分钟；若member600秒未完成，由原预算失败并检查原因，不能盲重跑千次请求。

工作目录和DAGSTER_HOME沿第23.2节；以下按序执行，Raw三项分别使用本轮`resume_20261025/dc-index-run-config.json`、`dc-member-run-config.json`、`dc-daily-run-config.json`。每项SUCCESS及check通过才推进：

```sh
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job raw_tushare_dc_index_update_job --partition 2026-10-22 --config ../reports/datasets_recovery_20261022_20261024/resume_20261025/dc-index-run-config.json
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job silver_dc_index_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job raw_tushare_dc_member_update_job --partition 2026-10-22 --config ../reports/datasets_recovery_20261022_20261024/resume_20261025/dc-member-run-config.json
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job silver_dc_member_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job raw_tushare_dc_daily_update_job --partition 2026-10-22 --config ../reports/datasets_recovery_20261022_20261024/resume_20261025/dc-daily-run-config.json
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job silver_dc_daily_update_job --partition 2026-10-22
```

最终一次6文件schema、22日行数/唯一键及邻日stat验收，复用6个原生check，不重算全历史。通过才扣减6项。若上游proof需要未批准历史读取则该链停在proof前，可继续已就绪的独立指数链。

## 25. 股票分钟区间完成记录：待确认的最小修正方案与LLD

实际Prod任务16729已成功：time_input为range 2026-10-22..2026-10-23，29605单元全部完成、失败0、progress100、fetched/saved3594514、rejected0、五频无股票过滤。DG共享候选SQL却只查time_input.trade_date=22日，因而返回prod_ops_task_run_missing；不是本次Prod数据没采完。本轮先方案，不擅自改门禁，也不让管理员重采约180万单日行。

建议只修DG两文件：`prod_db/stk_mins_task_run.py`的候选日期过滤与共享row判定，及`bootstrap/stk_mins_raw_replace_from_prod.py`相同独立候选SQL；CodeGraph已核对shared probe→row parser、by-id→同parser、离线select→同parser，影响21个符号。所有reference消费者沿原字段，不改Prod、DatasetDefinition、频率、对象池、Raw/Silver业务写入或其他数据集。

同一日期归属判定只接受两种合法时间输入：point精确等于目标日；range起止合法、start<=end且包含目标日。无效日期/混合输入/反向/不含目标日拒绝，不按任务创建日或结束日猜业务日期。候选SQL必须在LIMIT20前按目标日所属范围过滤，不扩大到全表；共享parser再按真实日期类型严格验证。by-id继续复用同一判定。其余原安全门槛全部保留：同数据集maintain、success/ended、五频完整、无股票过滤、units完整、failed/rejected0、progress100、fetched/saved>0；目标22日预期代码五频EXISTS覆盖全部通过才生成reference。

reference.trade_date仍是22日，真实task_run_id16729和真实ended_at原样保存，不把Prod区间任务篡改为point；Raw每频按同ID/结束时间/日期归属和目标日覆盖复核。单日计数、单股或部分频率/部分完成记录不能替代。

开发前仍需确认SQL日期合法性实现依据和既有全部测试；不得引入未经核验的PG版本/函数假设。正向测试用真实16729任务形状及独立字面日期；反例覆盖不含日期、缺边界、非法/反向/混合时间、非success/缺ended、单股、少频、未完成/拒绝行；同步shared/by-id/离线消费者，保留原point及已有reference测试。真实验收只读16729一行及5576预期代码×5频的索引存在性，不重新读取OHLC/成交量或全日明细。通过后再补批次7实际命令、引用和读写预算，未获该修正确认前不编码、不启动股票job。

## 26. 板块批次4/6历史读取申请范围（待明确批准）

目录/stat测算：2024-01-02至22日已有Silver dc_daily676文件、37531917字节（35.793MiB），最末21日，22日待本批生成，之后约677文件；同期至21日Raw dc_daily676文件、37548141字节（35.809MiB）。日历full文件89590字节，尚未读内容；不能把普通工作日没有文件当成交易日缺口。

必要性：Gold指标按现行公式从2024-01-02建立历史窗口，当前入口不能只读22日；若分类中有缺行情板块，Raw历史身份也用于判断是尚无首条行情还是历史漏数。请求范围只为这两步：

1. Raw dc_daily历史至21日，仅ts_code/trade_date及schema/footer，且只有index−daily有差集时读取；约35.8MiB/轮，64文件一批，最多11批/33条重SQL加日历查询，512MiB/2线程/no-spill、每SQL1秒/整轮5秒，128MiB/200万投影行上限。源确认和三个Raw执行前复核/成员末端复核可能重复，限定本批合计最多8轮（不超过约287MiB文件输入），无差集则0轮；失败不盲重试。
2. Silver dc_daily 2024-01-02至22日约677文件、约35.85MiB，读六列ts_code/trade_date/category/close/high/low，32文件/批约22批，临时表单次计算，只写22日Gold一个文件。现行资源上限16GB、4线程，spill上限512GB，临时目录为既有卷；旧基准611日单日0.664秒/526MB只作参考，本次源读/算/写/读回目标仍≤15秒，超限先查原因，不自动重跑全历史。

最后check只读22日Gold/Silver各一个文件，不再扫历史。正常最多一次Gold历史计算；若失败需要第二次历史读取，先报告失败与已提交现场，不将本次批准解释为无限重跑。Gold及check通过后才运行本机CH/Prod CH同日发布，写入范围仍只22日；既有原方案和本轮批次授权继续适用。未获全局读取明确批准前，此批只做元数据预算，不运行Gold计算。

### 23.3 普通指数正式结果

三个原生job均SUCCESS：Raw `ed393884-901d-42a4-9eb2-1c910587cd4a`（114.84秒）、Silver `119a58d8-361f-4b84-91bd-5999b1bf5a45`（2.90秒）、Gold `42bdaea4-28db-463b-971b-4feb5f231c70`（2.93秒）。19项物化/19项blocking check全部通过；一次19文件读回schema/22日计数通过，21/23邻日stat不变。见`resume_20261025/batch3-final.json`。本轮已补19项，剩余65→46，原109缺口累计补63项；没有全局重审。终端日志为空但原生DG事件已保存完整运行/check证据，未因空日志重复执行。

### 25.1 进一步真实核验与必要分区

独立调用现有主键索引覆盖检查（非OHLC扫描）确认22日5576个预期代码在五频全部存在，缺码0，耗时8.14秒；证据`resume_20261025/stock-coverage.json`。因此当前识别问题只在完成记录的时间输入，不是预期代码缺失。Raw分区`cn_a_stock_mins_trade_days`已注册；实际Silver分区`cn_a_stock_mins_silver_trade_days`尚未注册22日，不能把Raw分区已存在误写为Silver也存在。后续若推进股票Silver，需要在正式执行卡明确只增加该集合中的2026-10-22一个分区键，先核已存在则不重复写；不启停sensor、改cursor或批量注册历史日期，按该阶段授权执行。

### 26.1 股票后续年度文件元数据预算（未读明细、未批准执行）

仅目录/stat测量的保守上界（未按5576预期池过滤）：2026年度QFQ每频5592文件、七频39144文件，8072911121字节（7.518GiB）；指标年度同样39144文件、18441797624字节（17.175GiB）。21日state七频均存在、每份约250.7KiB，22日state均不存在。QFQ及指标合并22日时只写2026年度文件，保留其他日期；实际目标证券及文件数须在22日Silver生成后冻结，不能把七资产当七物理文件。

当前MACD入口额外发现2025及2026 QFQ年度源，先投影ts_code/freq/trade_date/trade_time/high/low/close并筛trade_date<=22日到临时表，之后才挑目标日和KDJ前8条；已有21日state也不消除前面的历史读取。2025 QFQ38241文件，9463368040字节（8.813GiB）；两年源上界77385文件、17536279161字节（16.332GiB），再合并2026既有指标文件。压缩字节不等于实际7列扫描字节/临时表内存，不能按只读22日或只读2026估算。此处仅记录代码和元数据，后续须按实际范围另做全局读取审批及中断/最终验收预算，未执行年度扫描或改代码。

### 25.2 SQL能力核验（只读）

Prod当前PostgreSQL版本号160013；pg_input_is_valid(text,text)存在，合法日期2026-10-22返回true、非法日期2026-02-30返回false。见resume_20261025/prod-date-validation-capability.txt和prod-date-validation-behavior.txt。建议候选SQL在LIMIT20前使用canonical ISO格式及该函数校验、再按point/range目标日归属筛选；不用裸::date导致坏记录中断。仅核验能力，尚未实施代码修正。

## 27. 2026-10-25 本轮实际收口与待确认项

普通指数批次3完成19项；板块批次2完成6项。合计9个原生job全SUCCESS、25项blocking check通过；两份批次final报告各仅一次目标文件schema/同日计数读回，板块还核对唯一主键，21/23邻日stat均不变。25个正式新文件，没有覆盖已完成44项，没有修改传感器、cursor、daemon或分区，没有写Prod业务数据、安装依赖或提交Git。

板块实际行数：分类Raw/Silver各1043、成员各98530、行情各1043；成员原生metadata确认1052请求、1051页、1次重试，失败/空代码均0，与Prod成员差集0，202.90秒读写阶段、208.42秒Dagster任务，未超过原1200/600秒预算。源分类/行情无差集，历史覆盖证明SQL为0。来源proof/config仅代表本次冻结输入，未来重跑须按原合同重新取得，不能照抄过期proof。

从原清单扣减：此前65→本轮25→剩40，原109累计恢复69；40项为股票链35、成交额Gold/Prod2、板块技术指标及两处CH3。当前清单见resume_20261025/remaining-assets.json；该数不是重新审计当前全目录的结果。

待管理员确认的两项问题已异步提出：第25节DG最小区间任务识别修正（未编码）；第26节板块历史读取（未执行）。股票来源物理代码覆盖已通过，不能继续称其源为0行，也不能跳过原门禁启动Raw；Silver22日分区登记纳入该阶段执行卡。股票后续年度/两年MACD源仅测元数据，尚未授权或执行全局内容扫描。两个必要条件外的已就绪批次已全部推进到本次验收；未把待确认事项算作完成。

证据：resume_20261025/summary.json、batch3-final.json、batch2-final.json、9份job-verified.json、来源计数、stock-coverage.json及Prod16729投影。所有只读审计脚本存为*.py.txt追溯；正式数据只由已有原生job写入，没有新建执行旁路。

## 28. 管理员要求先处理股票分钟线：本轮建议（待设计确认）

已按最新问题重新核对当前两处point-only候选SQL、共享parser、按ID复核和reference消费者。完整最小方案补入[完成门禁原LLD的2026-10-25本轮建议章节](../../docs/design/dagster-stk-mins-prod-task-run-readiness-low-level-design.md)：保留正常明确trade_date的单日任务（包括原无mode形式），新增显式range且合法闭区间包含目标日；混合/未知模式明确拒绝。两处SQL共享日期条件且先筛日期再LIMIT20，parser再次校验，完成度/全市场五频/目标日覆盖均不变，reference仍按单日冻结真实来源ID与结束时间，不改变其他数据集或Prod。

本轮先处理日期识别，再按原生任务补22日股票Raw/Silver10项，最后一次限定验收；Silver仅登记22日一个缺失分区键。后续前复权、指标、九转在股票链内继续按依赖推进，但原年度/跨年读取预算与审批要求仍保留。当前用户在询问修改方案，本轮没有把该问题当作已确认全部设计，没有修改Python、运行测试、写Prod/Lake/instance或启动正式任务，剩余仍40项。

## 29. 已确认修改方案，本轮只修复和验证任务日期识别

管理员基本认同第28节方案，并明确：测试不必发生真实分钟读取，修改范围只是判断Prod任务是否成功覆盖目标日期。最新边界优先于此前建议的连续补数步骤。本轮仅改两份DG生产实现：共用TaskRun日期判断和候选SQL、离线恢复的同类候选SQL；保持其他任务成功条件、reference、分钟覆盖、Raw/Silver读写逻辑不变。完整代码点、正反用例、读写范围、失败规则和性能预算已先更新到[原LLD最新章节](../../docs/design/dagster-stk-mins-prod-task-run-readiness-low-level-design.md)。

原流程已在WHERE中按trade_date筛选，再排序并LIMIT20；这次只扩展日期条件为合法单日匹配或显式range闭区间包含目标日，20条上限不变。无mode指缺键，原明确trade_date记录继续有效；显式null/空mode、未知模式及混合非空日期明确拒绝。

验证使用独立字面日期样本、隔离替身、READ ONLY日期CTE和有界ops.task_run投影。真实读取限定原16列、22/23及区间外21/24候选各最多20条、ID16729一条；不读分钟表或Lake，不生成真实completion reference、不登记分区、不运行补数job。每SQL15秒/整段30秒目标、报告1MiB上限；本轮结束时剩余数量保持40，日期识别通过不等于补数完成。

### 29.1 修复及限定验证已完成

已修改共用`prod_db/stk_mins_task_run.py`及离线恢复`bootstrap/stk_mins_raw_replace_from_prod.py`的日期识别；按ID复核继续用相同parser。新增独立日期回归文件，其他成功条件、分钟覆盖、reference、Raw/Silver业务流程与其他数据集未改。CodeGraph explore/impact和开发后sync/status已完成，完整硬口径对账见[原LLD最新章节G节](../../docs/design/dagster-stk-mins-prod-task-run-readiness-low-level-design.md)。

| 核验 | 结果 |
| --- | --- |
| 修改前已保存16729形状 | 旧parser拒绝22/23，缺陷复现 |
| 日期及原TaskRun隔离回归 | 145项新增+7项原用例通过 |
| 既有受保护回归 | 连续性26项、静态门禁113项通过 |
| 只读日期SQL样本 | 43项通过；两入口均先排除25条干扰记录，再取最多20条 |
| Prod真实候选及按ID记录 | 21日16642、22/23日16729、24日空；16729仅对22/23有效 |
| 真实分钟/Lake读取、补数及分区写入 | 均未执行，剩余仍40项 |

证据为`task_date_fix_20261025/`下的before-fix、pytest、protected-*、date-verification及SQL结果。实际远程操作只有READ ONLY任务投影和查询内日期样本，没有访问分钟表；SQL脚本约0.174秒完成，未安装/升级依赖、未提交或部署。原TaskRun文件5项HEAD已有Ruff风格问题无新增，细节在ruff-baseline.json；致命错误、新测试和另一修改文件检查通过。测试收集连续性时发现需使用原受保护启动器，已按原入口完成，没有修改防护或过滤失败。

## 30. 提交后继续股票分钟链补齐（2026-10-25）

管理员已明确要求提交修复并尝试推进股票分钟线及下游。已在dev-interface提交`2405c620 fix(dg): recognize stock-minute task date ranges`，白名单仅两份生产日期识别实现、新测试和原LLD四文件；无push或部署，其他脏文件保留。第29节“不读取分钟/不补数”是已结束的代码验证阶段；以下转入本次新授权的正式补数，不重复用分钟读取测试日期识别。

### 30.1 股票Raw/Silver：方案、LLD与预检约束

本步复用原LLD F与分钟staging专项已通过实现，仅处理2026-10-22的Raw5/Silver5共10项。先限定只读预检：只看这10目标和21/23邻日的stat；检查两个原生job的活动run（各最多10条）、两个实际动态分区集合是否含22日；只检查同日stock_daily、suspend_d和当前股票身份/Basic依赖文件，不重复审计其他数据集。使用现行股票池函数取得22日预期代码，调用原完整TaskRun+五频索引EXISTS门禁一次，冻结真实来源ID/结束时间/覆盖计数的新reference及原config builder输出；这是正式导出的必要准入依据，不是额外分钟数据测试。

只读连接采用现有PostgresRunStorage/PostgresEventLogStorage且should_autocreate_tables=False，不初始化正式instance；不输出凭证。Prod只读投影仍为原16个TaskRun字段，候选最多20条；覆盖只读freq/ts_code/trade_time身份索引，不取行情明细。预期5576代码，五频共27880次索引存在性；旧8.14秒测量作预算参考，本次整个预检目标30秒。原Basic/身份依赖及同日日线/停牌按原执行合同使用，不更新上游。LOAD postgres只用既有扩展，禁止INSTALL。

预检若通过，再登记实际缺失的cn_a_stock_mins_silver_trade_days中的2026-10-22一个键；Raw集合cn_a_stock_mins_trade_days已有键则不写。不启停sensor/daemon，不改cursor、分区模型或其他日期。正式写入前保存精确命令和新鲜config，确认无目标冲突、无活动writer、卷挂载/同设备/空间充足；以下命令使用现有.venv，工作目录为/Users/congming/github/goldenshare/lake_console/orchestrator，DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home：

```sh
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python3 -B /private/tmp/dg22_stock_resume_preflight.py
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python3 -B /private/tmp/dg22_stock_register_silver_day.py
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job stock_mins_raw_update_from_prod_job --partition 2026-10-22 --config ../reports/datasets_recovery_20261022_20261024/stock_resume_20261025/stock-raw-run-config.json
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job stock_mins_silver_update_job --partition 2026-10-22
```

Raw仍为reuse_existing，缺失才导出；Silver仍为默认write_new。源五频全5577代码计数上界1804297行，实际过滤22日5576池；只读22日Prod一次/频，Raw共5文件。Silver只读本频Raw、粗频另读同日Raw1m，以及身份/同日日线/停牌，输出5文件，不读年度分钟历史。正式外部staging、receipt和同设备逐文件提升均沿现行writer，不改业务SQL和既有检查。

执行与最后验收预算：Raw/Silver合计5—20分钟、候选/receipt/日志1GiB；当前代码为Raw每资产3项共15项、Silver每资产4项共20项，合计35项原blocking checks须通过，每job终态SUCCESS后才推进。Silver引用覆盖还读取当前silver_stock_lifecycle，预检补该正式依赖文件，不能误作旧namechange。每60秒以内查看本run小型进度；无进展先检查本run，不重复launch。中断后保存run_id/已成功正式文件/receipt；只处理实际未完成范围，不盲重跑或覆盖。最终最多500本run事件、一次10文件schema/22日计数/代码与键汇总及邻日stat，目标3分钟，不做全局审计。预检不满足即停该链，其他安全条件不放宽；成功仅将40项减为30项，后续成交额等另落执行卡，年度/跨年全局读取仍须按实际范围明确批准。

### 30.2 本次预检结果与执行依据

`stock_resume_20261025/preflight.json`已确认十目标均缺失、两writer无活动run、daemon未运行；五份上游依赖（Basic/身份/生命周期/22日日线/停牌）存在，卷已挂载、Lake/staging同设备且空间足够，LOAD postgres通过。22日预期5576代码、hash=ba874499bfc6e1145ea0002088484244；新代码选中16729，目标日五频代码覆盖全部通过，完整预检1.049秒。新reference和五资产config已由现有builder写入`stock_resume_20261025/stock-raw-run-config.json`；没有用旧日期测试结果代替正式准入。

Raw日期分区已存在；Silver确实缺22日，登记只写一个键，前后状态保存为silver-partition-registration.json。登记脚本的15分钟预检窗口只是避免使用陈旧的现场检查，不改变reference合同，也不宣称reference有TTL。随后严格执行30.1命令，未通过前不进入Silver。

运行结果核对复用已审计的dg22_verify_batch脚本，仅把报告目录切换到stock_resume_20261025，未另写资产或检查逻辑。Raw/Silver各终态后运行`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python3 -B /private/tmp/dg22_stock_verify.py verify <原job名>`，最终仅一次`... /private/tmp/dg22_stock_verify.py final 7`；检查须绑定同一次本资产物化，35项均blocking/passed。脚本以.py.txt保存供追溯，不接入正式Definitions。

### 30.3 Raw/Silver正式结果

Raw run `ea31d235-8eee-4962-a006-9f114e87d18e`为SUCCESS，91.58秒，5物化/15检查全部通过；Silver run `b761abc1-e060-4184-b11f-7b09c6f350b8`为SUCCESS，16.08秒，5物化/20检查通过。十个新增文件仅做一次限定物理读回，schema/日期/唯一键通过，21/23邻日stat不变；见`stock_resume_20261025/batch7-final.json`。Raw五频均5576代码，行数1354376/275336/95496/50536/28232；Silver五频5570代码，1342370/272930/94690/50130/27850行，按原停牌及收盘后时段规则处理，引用覆盖检查通过，不能按Raw/Silver机械行数相等判断缺失。

本批新增一个Silver22日分区键；不改其他日期、sensor/cursor或Prod源数据。剩余40→30，原109缺口累计补齐79；此数由原清单扣除本批10项，不是全局重审。

## 31. 成交额Gold及Prod发布：方案、LLD和执行卡

Raw/Silver本批通过后推进原批次8，不改代码或合同。现行`gold_wealth_market_turnover_update_job`选择Gold和Prod两个资产及1项Gold blocking check，分区复用cn_a_stock_mins_silver_trade_days的22日；先Gold及检查通过，再发布Prod。当前实现已沿CodeGraph核对`wealth_market_turnover_contract`、Gold资产/check、`wealth_market_turnover_prod_core`和`prod_db/wealth_market_turnover.py`。

读取仅22日五份Silver股票分钟及22日Silver日线，共6文件，分钟聚合投影ts_code/freq/trade_date/trade_time/vol/amount，日线用于原北交所收盘残差处理，单位仍vol×100/amount×1000。原writer至少3轮同日聚合，加schema/键/残差检查及提升校验，不能预算为一次读取；不读年度或其他日期分钟。执行前只stat这6输入总字节、Gold目标和21/23邻日，不重审上游；检查同job无活动run、staging同设备。

Gold只生成`gold/wealth/market_turnover/trade_date=2026-10-22/part-000.parquet`一个文件5行；随后原生Prod writer在单事务中replace `core_serving.wealth_market_turnover_snapshot`中`type=stock/market=CN_A/trade_date=2026-10-22`五频范围，显式14列为type/market/trade_date/freq/build_status/latest_trade_time/total_amount/total_vol/security_count/source_row_count/points_json/build_version/built_at/build_note。原事务内readback逐字段相等及points_json hash必须通过，提交后再做一次仅同范围5行的持久化读回；不写Prod Raw，不涉及其他日期或表。管理员原批次及本次“下游补齐”授权覆盖该具体Prod发布，不冒称纯Lake任务。

预检Prod只经现行psql-remote脚本READ ONLY统计21/22/23该type/market的行数和小型摘要，22日预期0，若已有数据先核清，不直接覆盖。Gold若已存在同样先停核对。预算按实际6文件stat冻结，逻辑文件输入保守1GiB、候选/日志64MiB、运行含CLI3分钟；超限或失败查当前run/Gold/Prod现场，不能盲重跑覆盖已完成Gold。writer失败可能清理本次候选，不声称年度receipt续跑能力；若只有Prod失败，先保留Gold，再单列精确继续步骤。验收仅本run≤100事件、2物化、1检查、Gold5行与Prod事务内及提交后读回，无全局审计。邻日Gold stat和Prod小型摘要保持；成功后30→28。

工作目录、DAGSTER_HOME沿30.1；预检和一次正式命令：

```sh
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python3 -B /private/tmp/dg22_turnover_preflight.py
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_wealth_market_turnover_update_job --partition 2026-10-22
```

本轮新预检与Prod摘要保存在stock_resume_20261025，正式命令输出turnover-launch.log；只有Raw/Silver35 checks通过且该预检通过才运行。

原batch verifier只支持物理Lake路径，不能把Prod资产URI当成Parquet去stat；因此本批使用单独的临时只读核验脚本，复用现行14列合同及归一化比较函数，仅核2资产事件、1检查、Gold5行和psql-remote导出的同范围最多6行（第6行用于抓异常多行）。不复制聚合公式，不创建正式入口或新的业务事实源。提交前后Prod邻日摘要由相同14列规范排序计算，只输出行数/hash；源points_json不会整表导出。

### 31.1 成交额预检已通过

6个22日输入合计31283049字节（29.834MiB），Gold目标缺失、同job无活动run、Silver分区已存在；Prod目标22日stock/CN_A为0行。21/23 Gold stat与Prod摘要已冻结，详见stock_resume_20261025/turnover-preflight.json及turnover-prod-before.json。按照既定一job/2资产/1检查执行，不增加来源扫描或改公式。

### 31.2 成交额正式结果

原生run `02867f13-7a55-4fcf-9d1d-3bdfa8ed92d3`为SUCCESS，2.93秒，Gold/Prod两资产物化和1项blocking check通过。Gold5行与Prod事务内readback5行一致；独立psql-remote提交后限定读回仍为5行，完整14字段相等，points_json hash=adf3231462665db3860f056f64381858。6输入stat、21/23邻日Gold stat及Prod对应摘要均不变，见stock_resume_20261025/batch8-final.json。剩余30→28，原109累计恢复81。

临时核验脚本首次用未加前缀的metadata键取摘要，报KeyError；已根据当前metadata builder核明扩展键统一在goldenshare/下，纠正为精确键后只重做小型结果核对，没有重跑job、重新聚合分钟或再次导出Prod。当前Gold旧检查事件partition字段仍为null（未改造存量检查定义），本轮按目标materialization ID绑定同run的22日物化，并核了实际22日文件；不把null字段说成已修复或已写入22日。

## 32. 股票年度QFQ读取范围与预算（待明确批准）

**旧申请记录，现已撤回。** 本节三次SHA与旧粗预算未获批准；管理员明确暂停修复、只做代码/已有证据审计。最新一遍摘要、整链合并读取、总量测算及推进步骤见第34节和原LLD第9节，不能使用本节启动任务。

下一批9不能按“只补22日七个文件”理解：目标是每个有当日数据证券的七频2026年度文件，需保留其他日期，因此必须读取并合并这些年度内容。当前目录/stat保守上界39144文件、8072911121字节（7.518GiB），实际集合在当日Silver/派生窗口身份上冻结；不写2025，也不读2025 QFQ或历史factor。输出完整11列ts_code/freq/trade_date/trade_time/open/high/low/close/vol/amount/exchange，计算依赖只取同日Silver与22日silver_adj_factor（两组factor参数指向同一路径）。同日因子修复门禁仍按原合同，不跳过。

共用publication原实现：既有年度目标一次身份列检查、一次全11列合并COPY；候选身份检查、重复键GROUP BY及count，正常每候选三次完整SHA（validated、全批提升前、替换后），每文件building/validated/promoting/promoted四份小JSON并fsync，另候选/目录flush。28 checks由7个multi_asset_check共享诊断产生，各频4结果；path_mismatch仍检查全年度身份，目标日取值/键/覆盖限制22日，schema读全部实际目标footer；不能把检查预算当成0历史读取。

因此申请范围包含2026受影响年度QFQ一次正常合并、候选/正式摘要校验和原28检查；同范围中断最多一次续跑也要计入。已promoted文件续跑会读正式SHA两次，validated候选续跑保留三次SHA但不COPY，building重建；入口仍重算/冻结当日replacement，并非全部不重新计算。连续失败先停，不无限重扫。年度旧/候选、冻结replacement及20%余量保守预留12GiB（按实际目标/新增行重新校准），现有DuckDB16GB/4线程/既有卷spill512GB上限保持；压缩文件大小不等于解压内存或总IO。至少3次新年度hash约22.6GiB，加旧身份/合并/候选检查/正式checks，因此不把7.518GiB当全部读取开销。

批准后按原staging LLD先做每频1代码真实有界性能样本、隔离写到/private/tmp，原正式源stat不变，样本输入不得扩到其他年份；据实际文件/行数/耗时冻结全市场预计耗时及拒绝上限，再启动原生stock_mins_qfq_daily_update_job。样本与全市场执行分别记证，样本不能作为全市场完成。正常执行仅一次，若需要同根续跑先记录已完成文件与原root_run_id。完整7资产/28检查通过后只做当前目标聚合，不重读年度明细做公式重算。

MACD批次10另需2025+2026 QFQ七频约77385文件/16.332GiB源及2026指标约17.175GiB合并，21日state不免两年读取；九转批次11主分钟入口也先读2025+2026四频约44220文件/1.538GiB、LAG后才筛目标日，缺seed还可能对最多500代码走所有年份fallback。两者不纳入本次QFQ年度读取申请；须另冻结实际范围和预算再批准。现有“九转有限历史”只描述依赖意图，不能充当该实现已按20日裁剪的证据。

## 33. 本轮收口和待批准范围

代码提交仅2405c620a四文件，未push或部署，其他工作区改动保留；后续本轮执行说明及预算继续写入原文档，未扩展正式代码修改。正式3run均SUCCESS，新增11个Lake文件（Raw5/Silver5/成交额Gold1），Prod成交额5行，36项checks全部通过；另补一个Silver22日分区键。股票十文件只核对一次，成交额只核5行小输出和提交后5行，无全局重审、无重跑已完成任务、无sensor/cursor变更、无安装。

剩28项按旧缺口清单减去本轮已验证12项得到：前复权七频7、MACD/KDJ指标/state14、九转4、板块技术Gold/两处CH3。完整清单与本轮统计见stock_resume_20261025/remaining-assets.json和summary.json。当前股票分钟源与日期识别都已通过，不再作为阻塞；下一步是第32节受影响2026年度QFQ读取的独立批准，已向管理员发出申请。板块和MACD/九转其他历史范围保持各自审批边界，未将一次继续指令当成全局读取批准。

## 34. 暂停补齐后的前复权整链读取审计（仅文档，未开发）

本节保留上一轮只读审计时的方案及授权状态，后续开发、测试和当前阻塞以第35节为准。

管理员明确本轮只读代码和已有证据、写原文档，不改代码、不读新数据、不测试或补数；正常年度完整SHA保留1次，另2次不批准。第32节旧申请撤回，第33节“等批准即可继续”的说法是当时阶段记录；现在必须先完成读取优化及验证，再以新预算提出精确读取范围申请。

完整逐项裁定、实现位置、共享影响、配置使用、测试和继续规则落回[原写入方案/LLD第9节](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#9-前复权整链读取审计与优化方案2026-10-25)，正式28检查语义同步落回[原治理LLD第16节](../../docs/design/dagster-stk-mins-qfq-validation-governance-low-level-design.md#16-2026-10-25前复权读取合并的检查约束)。没有新建平行方案。

本次审计结论：来源与因子各asset/check一次载入并复用；replacement只生成1次；旧年度范围检查和合并共用1次；候选范围/全年dup/count共用1次；正常年度SHA只1次；正式28检查独立读取，内部每年1次并累计当日TEMP。删除的两次摘要由全体/逐文件/rename后身份核对承接；中断实际复用文件再SHA1次，同次进程不重复。共享publication会影响MACD/state提升与恢复，必须回归，但不取得其数据读取或重算授权。

预算必须计完整链，不能拿以前22.6GiB摘要数充当总量：

| 范围 | 拟优化后的读取/写入 |
| --- | --- |
| 正常总读取 | S+3C+2D+14A+P+Fr+Tr |
| 正常文件写入 | C+P+Fw+Tw；rename不再写一份年度 |
| 规模参考 | C≈旧目录7.518GiB时，计明确额外预留约31.524GiB读/8.143GiB写，非实测 |
| 讨论用执行预算 | 候选C暂预留8GiB等条件下，约32.969GiB读/8.625GiB写；向上34GiB读、9GiB写、正常额外空间12GiB |
| 最坏一次全部重建继续 | 正常+继续累计68GiB读/18GiB写；旧失败候选保留时额外空间最坏向上22GiB，继续前按现场重算 |
| 只重跑正式检查 | 读取10GiB预算、小型事件/日志写入，不重写年度；不是正常多做一轮验收 |

S只采用旧目录/stat的39144份/7.518GiB作测算背景，实际目标未冻结；新C及因子A/冻结P/元数据未实测。七资产来源必须按真实规范化映射重复计入：1/5用Silver1，15/30用Silver5，60/90用Silver30，120用Silver60，单阶段57243552字节，两阶段约109.18MiB。旧32996152的估算法漏了部分原生频率复用，本轮已纠正。所有假设及预算门禁在原LLD9.6表内，不按缓存或列数比例减额。

为排除隐含临时I/O，方案拟仅本次按日QFQ asset/check复用既有existing_no_spill连接策略，Tr/Tw=0才能使用新预算；不改全局16GB/4线程默认或其他消费者，内存不足即停。当前代码仍managed且3次SHA，34/9不是它的运行承诺或已实现硬上限；不允许拿新数字运行旧实现。系统预读、fsync/目录日志等物理设备I/O未实测，不能称已精确计算。

后续步骤：先在获准开发后落地一次SHA及继续规则并回归共享消费者；再合并来源、年度、候选、正式检查读取并通过独立语义/reader次数/无spill测试；随后另列实际目标/stat预检和每频1代码有界真实性能样本范围；依实际S/C/A/P/元数据和耗时校准预算；取得新的精确年度读取/写入批准并落执行卡后才补7项/28检查，最后仅一次限定验收。先不进入MACD、九转或板块。

还查到独立run-status sensor监听QFQ成功后可请求MACD下游；手动job本身不运行sensor/readiness，但不能据此排除自动任务。补数前须核daemon/sensor/活动run并确保不会越过当前授权；需要启停时另按该具体状态变更授权执行，不私自操作。日常巡检、factor repair、history不是34/9单次手动job预算的一部分，禁止以验收名义额外触发；时间预算也必须由样本加数万fsync开销校准，不能由GiB直接推算。

本轮只改上述三份原文档及本恢复计划的阻塞说明；0 Python改动、0新增Lake/数据库读取、0测试/任务/正式写入、0提交。既有263项测试只是旧staging实现证据，不计作本次优化验收。22日剩余仍28项。


## 35. 前复权读取优化开发与隔离验收（2026-10-25）

管理员随后批准按方案开发、再做测试，本轮已完成。原方案/LLD的[第9节](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#9-前复权整链读取审计与优化方案2026-10-25)为约束，[第10节](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#10-2026-10-25开发与隔离测试结果)记录逐项实现/验证；检查语义同步[原治理LLD第16节](../../docs/design/dagster-stk-mins-qfq-validation-governance-low-level-design.md#16-2026-10-25前复权读取合并的检查约束)。没有新建平行方案。

完成范围：日来源与factor各读1次到同一连接，replacement只生成1次；旧年度校验/合并1次；实际候选范围/全年重复键/行数1次；年度SHA正常和恢复均每实际文件1次；正式multi-check独立读取，每年度1次并在日TEMP上复用重复键/价格/身份/样本。日常asset/check显式无spill，其他连接默认、公式、28检查名称及结果、history/repair入口不变。共享publication统一覆盖QFQ和MACD年度/state的提升及恢复，未改MACD计算。

开发复核先后发现并解决两个问题：拆分时锁取得过晚，已恢复先检查参数/持锁再执行replacement，并用0 SQL反例保护；bind与第一次摘要之间的receipt变化，已用绑定时快照和全部记录预检拒绝。旧年度原始SELECT * TEMP保留原缺列/路径异常顺序；原SQL和修改前源码还独立确认D日/非D非法close均抛转换错误，纠正一处错误测试预期。没有以测试通过为由改变生产拒绝规则。

实际执行仅为代码编辑、隔离测试、静态检查和文档记录。隔离启动器保存在[qfq_read_optimization_20261025/run-isolated.py.txt](qfq_read_optimization_20261025/run-isolated.py.txt)，把临时DuckDB/Dagster目录放到临时目录，保持真实SQL、连接策略和原memory/threads设置；使用`/usr/bin/sandbox-exec`禁止网络和整个`/Volumes`访问。受保护套件使用原`tests/stock_suspend_confirmed_test_runner.py --scope regression --suite test_run_contract_static_gates.py`；没有绕过原启动器或安装依赖。

最终结果：20个相关套件297 passed、65 subtests passed，24.68秒；其中新增65个publication、26个asset/writer读取、32个正式检查用例已包含在总数中。另113项受保护运行契约静态门禁及5个subtest通过；全项目Ruff致命基线、其余改动文件默认规则通过。asset文件的7条既有默认Ruff问题与修改前code/message完全相同。CodeGraph explore/impact覆盖入口和共享消费者，开发后sync/status正常；独立复核未留阻断问题。

证据：[validation-summary.json](qfq_read_optimization_20261025/validation-summary.json)、[最终综合测试](qfq_read_optimization_20261025/regression-final.txt)、[受保护门禁](qfq_read_optimization_20261025/static-gates.txt)、[原转换行为核验](qfq_read_optimization_20261025/original-cast-evidence.txt)。正常及恢复的摘要次数/实际read字节、全体先验后逐文件提升、跨文件重复键、异构schema/异常、低内存停止和无spill均有独立反例；不以测试总数代替这些边界证据。

本轮新增正式数据读取/写入/run均0，0提交/0部署，未重复全局审计，恢复记录仍剩28项。进度日志已显示本次S/P/C stat字节及小输入/候选/正式摘要实际read字节，但这些不是设备I/O，34GiB读/9GiB写仍不是实测或自动硬上限。真实C/累计元数据写入、正式卷小文件rename、全市场内存/耗时尚待获准样本核验。下一步按原LLD9.9冻结精确目标/stat和自动下游边界、单独申请每频1代码真实性能样本，再校准并申请正式年度读取/写入；本轮停在这里，不进入补数。


## 36. 提交范围与下一步样本说明

本次按指令提交QFQ读取优化及其必要的未提交staging前置，含共享publication和MACD年度/state接入、对应测试/原文档。`assets/stk_mins.py`和股票分钟设计HTML只暂存QFQ相关改动，Raw/Silver等并行改动保留工作区，不借本次提交扩大到指数/ETF/资金流。提交不包含推送、部署或补数。

后续真实性能样本及不留临时文件的要求已写入[原LLD第11节](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#11-后续真实性能样本与清理要求提交前说明尚未执行)。建议先1只证券×7频，600000.SH七份完整2026年度当前stat合计1365658B（1.30MiB），加22日四份Silver和一份因子，共12份正式输入文件、30445345B（29.03MiB）。四份日来源虽按代码提取，预算仍按全文件计算。含准备复制、生成、一次摘要和原28检查，先列读取64MiB、临时写16MiB、空间32MiB的有条件额度；不是已执行或实测。当前仅stat，不读真实内容、不运行样本；不读取2025年，不测试MACD/九转。

样本所有副本、输出、candidate、receipt、DuckDB临时文件及profile同放独占父目录，正常/失败/中断先关连接释放锁再整目录清理；结束核对无残留，只保留小型结果报告。提交前隔离复验亦把pytest basetemp放到独占TemporaryDirectory，结束验证该目录不存在。


## 37. 获准真实样本首次执行未通过，已清理并停止

本轮严格按原LLD11节批准范围执行一次：600000.SH、2026七年度及22日四Silver/一因子，12固定正式输入，64MiB读/16MiB写/32MiB临时空间预算，原业务代码和28check evaluator。正式源只作一次准备读取；后续不追加全局审计、其他年份或其他证券，也未运行job/instance。

准备实际取得241/49/9/5行，共304行，因子1行；7个年度已复制到独占临时Lake。进入1分钟writer、来源与因子诊断后，publication构造调用tempfile.gettempdir()失败：隔离脚本只设DuckDB temp，遗漏系统TMPDIR/TEMP/TMP；sandbox正确拒绝默认系统临时目录写入。此为本次环境准备遗漏，不能宣称算法或数据失败，也不能把准备通过算作七频性能通过。

0/7频率完成，0/28检查执行，0年度摘要/提升；运行0.839秒只覆盖退出前部分。含Fr预留的文件读取计费33.042MiB，累计写约1.354MiB，未超预算；不是物理磁盘IO实测。12份正式输入前后5字段stat一致，正式数据写入0，无instance/job/event。整个`/private/tmp/qfq_perf_20261025_a1`已在finally删除，随后独立确认目录不存在、无运行进程。仅保留[小型说明](qfq_real_performance_20261025/README.md)与[result.json](qfq_real_performance_20261025/result.json)，没有临时Parquet、候选、receipt、runner或profile。

按11.5“不自动第二次读源”，此次停在报告，未改业务代码或自行重跑。下一轮建议启动Python前把TMPDIR/TEMP/TMP全部指向新独占目录内system_tmp，正式内容读取前验证gettempdir及小文件创建/删除，再按同范围执行；方案已落原LLD第12节，额外一次读取执行仍待明确批准。原始失败证据不覆盖。


## 38. a2获准重测：1分钟执行完成，报告转换失败，已清理

管理员明确批准修正后再按原方案测试。a2启动前统一TMPDIR/TEMP/TMP，在任何正式内容读取前验证默认小文件写删及publication构造；保留原12输入、单股票七频、64/16/32预算、临时Lake和原writer/check。

实际1分钟writer完成241条replacement、输出919587B，耗时0.161285秒；其check evaluator完成SQL并返回，耗时0.109377秒。报告转换先按tuple迭代TextMetadataValue而报错，未完成pass/name断言，故不能记四项或28项通过，后六频未执行。年度候选实际SHA1次919587B，冻结输入另1次7265B，提升后无重复SHA。

启动至退出0.989秒仅为已执行阶段；含Fr预留的全文件读取计费36.560MiB，写约2.253MiB，未超预算。源12文件stat不变，正式写入及instance/job/event均0。a2整个父目录已清除，a1也无遗留；未启动第三次读源。

已完成17项完全禁止正式卷访问的记录逻辑回归：准确复现旧异常，优先MetadataValue.value的修正通过9种真实类型、成功/失败AssetCheckResult、JSON写出读回及排他保护；该临时目录亦已删除。此结果只证明报告修正，不替代真实28检查。

证据为[a2说明](qfq_real_performance_20261025/retry-summary.md)、[a2原始记录](qfq_real_performance_20261025/result-retry.json)、[纯对象回归](qfq_real_performance_20261025/reporter-offline-validation.json)。按本轮执行卡12.1“再次失败不自动第三次读源”停在报告；下一次如获同范围/额度批准，应先同时完成环境与完整结果记录预检，再进入正式源内容读取。原始a1/a2证据均保留，不宣称全市场或正式卷性能通过。

## 39. 22日前复权七频正式恢复（已完成并验收）

管理员停止额外性能测试后，已明确批准原LLD第13节正常补数及年度读写范围。只处理2026-10-22七项QFQ，保留其他日期，2026年度范围，不含2025/MACD/九转/板块；读34GiB、写9GiB、额外空间12GiB，含原28检查，正常一次。确切入口、预检、读写与中断边界见原LLD13.1。

本次只做控制库只读预检和文件stat，然后运行原`stock_mins_qfq_daily_update_job`一次，不用样本runner或旧单文件final审计。已以本run七物化/28检查及现有publication记录验收，不再全局扫描。证据存`qfq_recovery_20261025/`；原剩余28项在本批实际七项全部成功后扣减为21项。

首次现场预检见[qfq预检](qfq_recovery_20261025/preflight.json)：无活动run，输入/代码/分区/空间满足条件；当时MACD日更、九转自动任务均为RUNNING。daemon虽已停止，未来启动仍可能继续消费此次成功，故当时尚未启动补数，先申请仅停止上述两个自动任务并保持停止，具体身份保留与失败规则见原LLD13.2；没有扩大传感器修改清单。

管理员随后已明确批准停用上述两项并开始补数。执行状态修改后保存读回证据，再运行原七频job，不恢复性能测试或全局审计。

- [ ] **TODO：等2026-10-23的数据补齐完成后，再启用`gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`和`gold_stk_mins_qfq_nineturn_update_job_sensor`。** 由后续补数执行者核对23日结果后执行并记录；本轮22日完成后继续保持STOPPED。

2026-10-25 21:24（Asia/Shanghai）两项已从RUNNING改为STOPPED并读回，cursor/instigator_data及其他自动任务状态保持原值，见[状态修改及启动预检](qfq_recovery_20261025/sensor-stop-and-launch-preflight.json)。现场无活动run/daemon，五输入stat未变、空间满足12GiB要求；没有重新列举年度文件。

已运行13.1原命令一次，run_id为`78a6791a-a540-42b3-9ac3-e27abda235c6`；第一执行资产为120分钟（Dagster按依赖选序，不人为重排job）。运行日志见[qfq launch](qfq_recovery_20261025/launch.log)。

### 39.1 正式结果

2026-10-25 21:24:26～21:39:41（Asia/Shanghai），run为SUCCESS，耗时914.629秒。7项22日物化、28项blocking检查全部通过，且每项check绑定本次相应物化的storage_id，没有借用历史通过事件。

| 频率（分钟） | 22日记录数 | 2026年度文件数 | 原检查通过 |
| --- | ---: | ---: | ---: |
| 1 | 1,342,370 | 5,570 | 4 |
| 5 | 267,360 | 5,570 | 4 |
| 15 | 89,120 | 5,570 | 4 |
| 30 | 44,560 | 5,570 | 4 |
| 60 | 22,280 | 5,570 | 4 |
| 90 | 16,710 | 5,570 | 4 |
| 120 | 11,140 | 5,570 | 4 |
| 合计 | 1,793,540 | 38,990 | 28 |

90/120分钟生成窗口分别16,710/11,140，与expected_window_count一致；incomplete_window_count及exchange_mismatch_window_count均0。七频年度文件均从本run的operation目标列表核对receipt：38,990份全部promoted，候选路径已不存在，正式文件dev/ino/size/mtime与已验证候选一致；五输入文件stat仍与执行前一致。最终只读JSON及stat，没有再次打开年度Parquet、重算SHA或执行额外性能测试。保留其他日期依据本次采用的原单日合并实现、既有回归和本run校验；本轮没有追加历史逐值比对。

详见[run及逐文件记录验收](qfq_recovery_20261025/run-verified.json)、[汇总](qfq_recovery_20261025/summary.json)。正式staging的继续执行记录保留；本轮两个操作脚本已从/private/tmp删除，源文本随报告保存，没有新增测试临时文件。

### 39.2 开销与剩余任务

七频最终completed记录与receipt字节汇总相符：旧年度S=8,055,561,219B、新年度C=8,094,696,789B、冻结输入P=31,370,988B；年度候选SHA实际累计读取C一次，正式文件重复SHA为0。D=57,243,552B、A=55,558B复用预检文件stat。按原公式含1GiB读取预留/512MiB写入预留，估算读31.255GiB、写8.068GiB，低于批准的34/9GiB；这些是文件大小及显式摘要逻辑读取记录的预算测算，不是硬盘实测IO。详见[成本核对](qfq_recovery_20261025/cost-budget.json)。

沿既有缺失清单，剩余28→21，原109项累计恢复88：MACD/KDJ及state14项、股票分钟九转4项、板块技术指标Gold/本机CH/Prod CH3项。本轮没有启动这些任务，也不把扣减结果称为一次新的全局完整性审计。

21:40最终[控制状态读回](qfq_recovery_20261025/final-control-state.json)：两个sensor仍STOPPED，无活动run、无daemon进程。**上述23日补齐后再启用的TODO仍未完成，不因本批成功而勾选。**

## 40. 剩余21项的后续补数计划（代码核对后建议，尚未执行）

本节回应管理员要求先列计划并确认是否需要开发。本轮只读当前代码、原方案和既有证据，额外只查询22日七条因子修复检查的控制库记录；没有读取年度/板块历史内容、运行新任务、修改业务代码或重做全局审计。

不能笼统承诺剩余21项全都不用改代码：板块3项、MACD/KDJ及state14项已有入口，目前没有发现必须新增业务实现的阻断；九转4项仍有候选位置和失败处理不符合现行规则的问题，执行前必须先单列修正方案/LLD并获准修正。不能因是现成job就直接运行。

### 40.1 建议批次及完成数

| 顺序 | 目标日期与内容 | 本批项数 | 通过后剩余 | 执行前条件 |
| --- | --- | ---: | ---: | --- |
| 1 | 2026-10-22板块技术指标：Gold → 本机ClickHouse → Prod ClickHouse | 3 | 18 | 复用现有三个job；冻结历史文件/读写预算并批准必要历史读取 |
| 前置处理 | 核清22日QFQ因子修复检查，按已有流程判断/处理必要修复并形成真实记录 | 不计新的缺失资产 | 18 | 七项记录现均缺失；先明确该流程读写范围，不手写通过事件，不跳过门槛 |
| 2 | 2026-10-22股票分钟MACD/KDJ七频指标及七频state | 14 | 4 | 因子检查通过、21日精确前序state齐备；批准2025/2026源读取及2026年度指标合并预算 |
| 3 | 2026-10-22股票分钟九转30/60/90/120 | 4 | 0 | 先修正候选位置/失败处理，核因子检查及21日九转前序，再批准必要历史读取 |

板块与股票指标没有直接依赖；建议先完成现成、读取量小的板块3项，避免等待股票前置处理和九转修正时全部停住。以上18/4/0是按既有清单推算的计划值，只有对应任务和必要检查实际通过后才更新当前剩余21。23日不混入本次22日补数；两个sensor继续保持STOPPED，仍按第39节TODO等23日数据补齐后再启用。

### 40.2 第一批：板块3项，复用已有实现

22日Raw/Silver六项及六检查已有成功记录：分类1,043、成员98,530、行情1,043行，见`resume_20261025/batch2-final.json`。来源无差集，不需要重复获取Raw历史覆盖证明或Tushare数据。顺序沿原`gold_dc_daily_technical_update_job` → `ch_dc_daily_technical_update_job` → `prod_ch_dc_daily_technical_sync_job`，每步通过原检查才进入下一步。

当前代码`assets/dc_daily_technical.py:139–214,637–743`为生成22日MA/MACD/KDJ/BOLL读取2024-01-02～22日Silver行情六列，32文件一批，只写22日Gold；候选位于正式staging。根据旧stat和已恢复22日文件记录推导约677文件、37,590,608B（35.849MiB），这是已有证据推导，并非本轮重扫。原Gold检查只读22日Gold与Silver，不重算全部历史。正式执行前补本批原LLD执行卡，核精确文件集合及预算，并按根AGENTS取得这段历史读取批准，不沿用QFQ34/9GiB额度。

两处ClickHouse发布只替换22日同一张表的数据，现有代码为同步DELETE后INSERT，不宣称整体事务原子；失败先做同日有界读回，再按失败步骤决定是否重跑，不重跑已成功Gold。Gold异常会清除未提升候选，不能宣称具有QFQ的逐文件receipt复用。具体失败/重试开销和同日验收写入执行卡，不为本批增加新的指标算法或改动其他日期。

### 40.3 第二批：MACD/KDJ及state14项，先处理真实前置

原入口`gold_stk_mins_qfq_macd_kdj_daily_update_job`只选七个成对指标/state资产及28检查。此前staging/逐文件记录修正已覆盖本入口。21日state必须是精确前一交易日，不以更早state或从零初始化代替。

控制库实查见[七项因子修复检查记录](remaining21-factor-gate-preflight.json)：22日`gold_stk_mins_qfq_factor_repair_plan_evaluated`七项均没有记录。这表示缺少独立流程的完成证据，**不表示刚补齐的22日QFQ行情缺失或其28检查失败**。`assets/stk_mins_qfq_macd_kdj.py:297`调用的门槛会据此拒绝MACD任务。先审阅现有因子修复流程的计划与读写范围，按真实结果补齐必要处理和完成记录；不得跳过检查或伪造通过。

现有daily计算会先读取2025+2026全市场QFQ，再提取当日和KDJ必要前序；21日state存在不会免除该读取。2026旧指标还需校验及合并；原check亦有独立源读取。必须逐项审计读取必要性，预算包括原28检查、中断后重新准备输入和最后验收，不能套用QFQ的S+3C公式或34/9GiB批准。旧目录stat仅作测算参考：2025QFQ9,463,368,040B，2026旧指标18,441,797,624B；本次实际QFQ2026变化用第39节证据，不能称旧两年上界为当前实测。

通过前置并获本批范围批准后，复用原job生成七频2026指标年度候选和七份22日state；预计指标涉及38,990年度文件，state行数可能含carry-forward，不能机械认定每频恰5,570。验收用14物化、28检查和本run记录，不再全局审计。此处尚未承诺未审完的读取实现一定零改动，也不以性能优化为由自行扩大开发。

### 40.4 第三批：九转4项，确认有必要的代码修正

当前`paths.py:531–547`返回正式Lake内的`gold/indicator/stk_mins_qfq_nineturn/_staging/...`；`qfq_nineturn.py:996–1046`在那里创建/写候选，原子替换后在finally删除残留候选。它没有复用前一批QFQ publication，旧候选还会在开头被删除。因此仍不满足候选只能位于`data_lake_staging`以及本次需要的失败留存/继续执行口径，不能直接补四项。

修正范围须先写回九转原方案与LLD：候选转到正式staging、同设备提升、失败/中断保留与继续依据，优先复用已有合适写入能力；不改变九转公式。先按批准范围做必要隔离回归，再执行22日四项。不得先改代码再补文档，也不恢复全市场性能测试。

读取范围也须核清：正常入口读2025+2026四频QFQ，前序是21日九转日文件的末根方向/count，不是MACD state；手动job不能绕过sensor原有因子检查要求。缺少seed的情况可能进一步读其他年份，且现有500代码限制晚于部分身份读取，不能把它当读取前的硬上限。执行前先核精确21日前序与是否会进入该路径，范围变化先获批准，不用20日窗口估算。

已有22日四频QFQ记录44,560/22,280/16,710/11,140，合计94,690；九转预期输出四份22日日文件，按原四检查验收，不覆盖其他日期。是否有历史追加读取、读几遍及失败续跑量均须写清后再申请执行。

## 41. 优先处理22日因子repair：实查26代码需历史修复（提案记录，已实施见42节）

管理员要求先处理七项因子检查再继续，并询问原repair为何没有触发。原`stock_mins_qfq_factor_repair_job`确实存在，手动QFQ不会串行调用；控制记录最近成功为21日，22日没有本轮运行记录。补22日QFQ时daemon没有运行，所以独立factor sensor没有自动接上；此前停止的是MACD/九转，不是factor sensor。这是前次手动补数顺序遗漏的一步，不把它说成repair已运行失败。

已作必要统计计数与26代码有界查询，不读历史分钟或年度内容：因子22日5,576代码、21日5,575代码，非法0；26只已有股票因子变化、1只合法新增、缺旧因子0。故当前不是只补七条日志的无变化情况，必须真实完成26只的历史前复权修复后，原op才会产生七条通过记录。MACD会直接被拦，九转自动任务也需这项；板块不依赖它。本节按管理员最新要求，优先准备repair，未执行其他批次。

证据：[计数及原job记录](factor_repair_20261022/count-preflight.json)、[26名单及文件stat汇总](factor_repair_20261022/scope-stat-summary.json)、[固定路径/身份清单](factor_repair_20261022/scope-stat-manifest.json)。3,111历史日期注册齐备，12,444份四来源Silver和3,111份历史因子均存在；source四频共47,307,734,197B，已存在26代码的年度目标1,932份/464,280,822B，理论上界2,366份。此处只是metadata，不据文件存在宣称历史业务数据已验收。

当前repair有可避免重复读取：每freq/year诊断后再从同源构造结果，相同来源也在目标间重复；仅源部分保守计费约174.04GiB，不直接按这个旧开销启动。原LLD第14节已提出复用现有relation/prepared接口，改为同年/来源只载一次、保留所有诊断，并传原root_run_id复用逐文件记录；目前尚未编码或测试。

提案正常一次按读52GiB/写3GiB/额外空间4GiB预算，只作用于固定26代码、2014-01-02～2026-10-22七频历史QFQ；不修改其他代码，不启动MACD/九转。失败停止，续跑最坏另52/3GiB及空间8GiB须按实际重新核准，不自动重读。完整实现/测试/中断及验收约束见[原LLD第14节](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#14-22日因子修复前置处理与读取修正方案待管理员确认未开发未执行)。管理员随后明确批准开发、验证及该范围一次执行，结果见42节，21项剩余数不变。

## 42. 22日因子repair代码修正及正式恢复完成

管理员明确批准LLD14，已先开发并验证，再正常运行原`stock_mins_qfq_factor_repair_job`一次。读源修正只在因子执行文件和原op：同年/来源共享原始TEMP，原诊断及公式读同一批行；历史因子年度复用、22日as-of run内复用；原root身份传给公共publication。公共writer、公式、检查口径、CLI配置及调度状态未改变。

既有15项及新增11项隔离回归共26项通过（5.75秒），三Python文件默认Ruff及差异检查通过，CodeGraph影响面审计和独立实现审查完成。隔离规则禁止网络和正式卷，测试临时父目录已删除；没有做真实全市场性能样本。详细硬口径对账见原LLD14.8和[开发验证](factor_repair_20261022/development-validation.json)。

| 正式结果 | 数量/状态 |
| --- | ---: |
| run | `f23ca4a2-b7c0-459f-9c55-764cb585db26`，SUCCESS |
| 耗时 | 112.514秒 |
| 修复股票 | 26只；合法新增1只不进入历史修复 |
| 原生1/5/15/30/60 | 1,380年度文件，20,202,727替换行 |
| 派生90/120 | 552年度文件，318,655替换行 |
| 合计 | 1,932文件，20,521,382替换行 |
| 本run因子检查 | 7项全部blocking/passed，22日及producer/batch/26名单hash一致 |
| 消费者判断 | ready=true，事件ID7726576～7726582 |

逐文件operation/receipt/stat验收全部匹配，所有源/因子/Basic/日历输入五字段身份未变。52次year/source载入对应12,444个来源文件，13次年度因子载入，91个目标批次；正常候选SHA仅一遍。S=464,280,822B、C=465,931,101B、P=453,330,654B，按原公式含额外预留估算读46.889GiB、写1.356GiB，低于批准52/3GiB；这些是文件/摘要字节及预算测算，不是硬盘实测IO。最终没有重新打开历史Parquet、重算摘要或重做全局审计，也没有失败重跑。

证据：[原任务日志](factor_repair_20261022/launch.log)、[run/检查/文件验收](factor_repair_20261022/run-verified.json)、[结果汇总](factor_repair_20261022/summary.json)、[真实消费者及控制状态](factor_repair_20261022/final-control-status.json)。实际执行源码SHA已保存于[预检](factor_repair_20261022/execution-preflight.json)。操作脚本从/private/tmp清除，正式staging的恢复记录保留；Git提交由后续提交阶段单独记录。

本次解除因子修复前置，**剩余资产仍21项**，不能因补七条检查再减七。后续MACD/KDJ14项除日更外还需按现行流程处理这26代码的历史指标修复，再核原读取范围/预算；九转4项仍需候选位置及失败处理修正，板块3项按原批次。本轮未启动这些任务。两个sensor仍STOPPED，无活动run或daemon；23日补齐后再启用的TODO继续保留。

## 43. 修改提交及22日板块技术指标三步补齐

因子repair代码、测试及执行证据已按40文件白名单提交 `1f54c5297`，未推送，其他工作区改动保留。本节板块执行是提交后的下一批，管理员单独批准历史读取和Gold→本机CH→Prod CH一次正常执行，读256MiB、写32MiB、额外空间64MiB，失败停止、不自动重读，不改代码。原方案/LLD见[板块LLD第15节](../../docs/design/dagster-dc-daily-technical-indicators-low-level-design.md#15-2026-10-22-板块三项补齐执行卡已完成)。

有界预检通过：677份历史来源共37,590,608B；22日Silver1,043个唯一业务键，来源身份与已恢复证据一致；Gold与两端CH22日都缺失，双端在线schema与V4的25列、引擎、分区和完整排序一致。两股票sensor保持STOPPED、daemon未运行、无活动run。首次Prod可选跳数索引元数据查询被权限497拒绝；没有业务写入，省去非必要清单后完成预检，无权限或配置变更。证据见[预检](board_technical_20261025/preflight.json)和[schema核验](board_technical_20261025/schema-review.json)。

三步均一次正常执行，无自动重跑：

| 顺序 | job/run | 结果 |
| --- | --- | --- |
| 1 | `gold_dc_daily_technical_update_job` / `4890e8c3-2221-46e5-99d8-bd14515a885b` | SUCCESS，1,043行，原blocking检查通过；run耗时7.526秒 |
| 2 | `ch_dc_daily_technical_update_job` / `dcf5f252-c3aa-4801-b13e-a5012a1f184b` | SUCCESS，1,043行，原blocking检查通过；run耗时7.137秒 |
| 3 | `prod_ch_dc_daily_technical_sync_job` / `76480b90-680d-428a-a467-c0219396175b` | SUCCESS，1,043行，原blocking检查通过；run耗时9.277秒 |

Gold原writer载入677份来源、664,211行历史，读/算/写/候选回读合计1,337.872ms，峰值内存739,016,704B（约704.78MiB），正式输出151,343B。MA/BOLL合法预热NULL保持原样，输入拒绝及重复键为0。Gold与本机22日24个业务字段逐键比较差异0；Prod原检查完成本机/Prod完整业务列与updated_at检查，缺键、多键、重复键、内容差异及时间落后均0。

最后只做源/邻日stat、目标日与邻日CH计数、控制状态核验：677份来源及日历身份未变，21/23日Gold身份未变，两端CH21日各1,043行、23日各0行保持不变；候选文件已由原writer提升、原路径不存在。两股票sensor仍STOPPED，daemon没有运行，无活动run。没有修改代码、配置、分区和sensor，没有新性能样本或全局审计；历史价格明细只读一轮。设备实际I/O及瞬时spill未单独采样，不能把35.849MiB源文件大小或现有计数当作精确磁盘读写量；CH内部parts/merge也不在文件写入计数中。

预检可选索引清单权限497和收尾报告metadata键前缀误用只发生在审计脚本；后者使用已保存的原run证据修正断言，未重跑业务任务或历史读取。三原run本身没有失败。完整证据见[本批汇总](board_technical_20261025/summary.json)、[本机完整字段比较](board_technical_20261025/local-full-field-comparison.json)及该目录三份run-verified.json。

## 44. 剩余18项与下一步边界

按原清单逐项销账，剩余股票MACD/KDJ指标7项、state7项，及30/60/90/120分钟九转4项；没有重新扫描其他数据集。因子repair前置已通过，不能把七项检查再次扣减为资产完成量。

MACD正确顺序是先22日日更生成14项，之后对26只因子变化股票完成历史MACD repair，再通过原14条repair completion检查；日更检查通过不等于历史修复完成。当前repair op会先检查历史state目标存在（包括22日），所以不能先跑历史repair。下一步只核当前代码、已有证据及必要文件metadata，确认每日及26股历史repair实际涉及的日期、目标文件、读写次数和空间，再落入原执行方案/LLD并申请对应历史读取范围；不增加真实性能样本或全局明细审计。静态复核未发现必须先改代码才能正常完成一次MACD日更与repair的已知业务错误；重复读取合并属于可选性能优化，不自动列为补数前置。repair op未传publication_id影响中断后复用原执行记录，不影响一次正常执行的计算结果，须在失败停止/重新执行的范围说明中明确，不据此扩展为整链改造。已知26代码2014～2026来源可复用因子publication记录，1,932份/465,931,101B；这不是整个MACD链的总成本，state合并需要保留其他股票，须另核目标文件数量与大小。source discover还会探前一年，不把可能的2013输入默认为已获批准。

九转当前paths.py仍将候选放在正式Lake的_staging，writer失败/续跑处理也需先按既定规则修正；未开发、未运行。MACD和九转的历史读取不在本次板块批准内，本轮没有启动它们。两股票sensor等23日数据全部补齐后再启用的TODO继续保留。

## 45. 22日MACD/KDJ日更及26股历史repair最小确认

管理员要求复用现成job，日更后执行repair。本轮不开发、不做性能样本或全局明细审计。最小确认只读控制记录和文件stat，结果见[预检](macd_recovery_20261025/preflight.json)。21日七state齐备，2014-01-02至22日3,111日×7的历史state仅缺22日七份；先daily后repair的原顺序可用。因子batch、26名单/hash未变，2013来源路径全部不存在，无需扩大历史范围。两sensor仍STOPPED、daemon无进程、共用pool空闲，空闲约2,715GiB。

日更按现行代码读取2025/2026 QFQ（共16.3695GiB）并合并2026指标年度（已有17.175GiB）；历史repair只读26股QFQ1,932份/465,931,101B，但要保留并合并3,111日的全市场state（现有3,837,207,000B）。文件级保守上界含原28检查、候选校验、冻结输入、临时工作集及最后验收：读约254.223GiB、写64.254GiB，提议正常一次读272GiB/写72GiB/额外空间64GiB，失败停止不自动重读。这是整文件大小上界，原checks对22日做列投影/日期裁剪，不能说成五遍全列历史读取或实测磁盘成本。

完整原job命令、配置、停止/中断、边界和验收见[原staging LLD第15节](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#15-2026-10-22-macdkdj日更及26股历史repair执行卡)，预算见[预算JSON](macd_recovery_20261025/budget.json)。未改业务代码；当前只是完成最小确认和执行卡，尚未读年度内容或启动正式job。

2026-10-26管理员已明确批准本批具体范围和272/72/64GiB预算，按daily→原检查→26股repair→原completion顺序各正常执行一次；不改代码，失败停止不自动重读。独立静态审查通过，现进入第一步。

### 45.1 已批准执行及中止事实

原daily run `b7b7a82f-cc07-4985-aa74-a0c3f1498936`仅启动一次，548.975秒后FAILURE。32GiB临时预留估低，TEMP文件达57.7501GiB；按批准条件中止，未扩大额度或自动重跑，repair未启动。第一信号中断1m年度候选COPY后，原独立30m步骤仍完成；第二信号使整run退出。不是发现公式错误或源覆盖缺失，也不能把中断解释为原任务自然完成。

保留15/30/120三频各5,570份年度指标及一份22日state，共16,713份正式文件、6个物化；普通28检查通过数0，因此本轮接受0项，仍待完成18项。1m保留53份已验证候选、1份building和5,517条未开始目标，没有1m正式提升。唯一收尾用receipt/stat确认来源及未提升目标未变、已提升正式身份与候选相符，未追加年度内容读取、SHA或性能测试。pool已空闲、无活动run，两sensor仍STOPPED。

[本批结果](macd_recovery_20261025/summary.json)、[receipt/stat收尾](macd_recovery_20261025/stop-reconciliation.json)和[原终态及中断事件](macd_recovery_20261025/daily-run-verified.json)保留实际失败事实。遗留20个本次DuckDB工作文件共57.7501GiB，启动前目录为空、进程已退出且无打开句柄；[精确清理清单](macd_recovery_20261025/spill-cleanup-plan.json)已提交确认，当前未删除。全部正式数据、候选、冻结输入和续跑记录保留，不因清理而重启补数。

此处停止后只做必要收尾与原文档记录；后续只需先根据已有执行证据确定剩余步骤、可复用结果及准确临时空间，再确认继续范围，不默认要求改公式、整链改造或新性能样本。

## 46. 已批准清理与仅补未完成步骤

管理员已明确批准删除精确20个DuckDB工作文件，保留正式Lake及staging续跑记录，只恢复未完成步骤；不再自行设置资源阈值中断。执行规则追加原staging LLD第16节，旧中断和预算不删除。先按清单逐项清理并记录，然后从失败run恢复四频及原28checks；日更保留15/30/120的6个父run物化，按6旧+8新核28检查，不重写已完成三频。其后仍按原26股范围执行现成历史repair和14条completion。

20项清理已完成（[结果](macd_recovery_20261025/cleanup-result.json)），正式/staging删除0。恢复采用原Dagster from-failure公共API，保留原root/partition/config，启动前核4写+28check并跳过成功三频；不另写补数计算，详见原LLD16.3。

日更恢复子run `31e25001-653a-40b8-8907-572891c30f95` SUCCESS：6父+8子物化、28原检查全部通过且跨run绑定正确；7频38,997文件receipt/stat收尾通过。已完成三频在daily阶段保持，进入原26股历史repair，未重跑日更。证据为 `resume-run-verified.json`及`daily-publication-verified.json`。

### 46.1 已完成结果（2026-10-26）

| 阶段 | run及结果 |
| --- | --- |
| 精确清理20个旧工作文件 | 62,008,688,640B；全部删除，正式/staging删除0，原目录保留 |
| 原job从失败恢复 | `31e25001-653a-40b8-8907-572891c30f95` SUCCESS，593.289秒；parent/root均为原b7 run，保留15/30/120六物化，只补1/5/60/90八物化；合并14项，28原checks通过且跨run绑定一致 |
| 原26股历史repair | `b1be4dde-70ef-45b1-aff2-0c82686a79c5` SUCCESS，384.611秒；2014-01-02至22日、七频，14条completion均通过且现成gate ready |

日更receipt/stat核七频38,990年度+7 state共38,997目标；已成三频在daily阶段未重写。repair核1,932年度/20,521,382指标行及21,777 state文件，state文件合计85,106,077行含保留其他股票，不把它误说成全体股票重算。repair按原26股范围合法修正包括已成三频在内的历史行，不是重跑全市场日更。所有candidate提升身份一致，收尾没有读Parquet正文或新SHA。

最后只核metadata：79,576条来源路径身份未变，595条范围外目标记录未变，无活动run、pool空闲，两sensor仍STOPPED。当前DuckDB工作目录为空；新计算工作文件已随正常结束释放，没有再次人工中断。原失败历史和staging的候选/冻结输入/receipt、原日志保留，不删除旧run或补写绿色事件。业务代码和原资源配置均未修改，无安装、真实性能样本或全局审计。

本次14项完成后，按原清单累计恢复105/109，剩30/60/90/120分钟前复权九转4项；该链仍需自身候选路径修正及读取范围确认，本轮没有启动。23日补齐后再启用sensor的TODO不变。证据：[结果汇总](macd_recovery_20261025/summary.json)、[清理](macd_recovery_20261025/cleanup-result.json)、[跨run日更验收](macd_recovery_20261025/resume-run-verified.json)、[repair验收及gate](macd_recovery_20261025/repair-run-verified.json)、[receipt/stat及控制收尾](macd_recovery_20261025/final-control-status.json)。

## 47. 分钟九转代码审计及原方案LLD补全（仅文档）

2026-10-26按管理员要求，先补[原九转方案第12节](../../docs/design/dagster-stock-qfq-nineturn-dataset-plan.md#12-2026-10-22四个分钟分区修正方案)和[原LLD第22节](../../docs/design/dagster-stock-qfq-nineturn-dataset-low-level-design.md#22-2026-10-22分钟九转写入修正与补齐lld)，没有新建替代方案。当前只完成代码审计与文档，不表示修正已开发或四项已补齐；原清单仍105/109，余4。

CodeGraph与实际实现确认：分钟候选仍由旧helper放在正式Gold的`_staging`；日线/分钟共用writer会删除失败候选，缺逐文件续跑；原source fingerprint不含实际读取的上一九转seed。仅分钟wrapper转接现有`StkMinsQfqPublication`并明确增加nineturn类型；不直接改共享日线writer，不另造一套恢复实现。plan在第一次查询前冻结stat、保留全部实际探查历史；writer绑定seed、路径集合、SQL/合同和校验版本，候选完整校验后仅一遍SHA，再同设备原子提升。日线同类旧路径是范围外待办，不能认定本轮已修好或继续按旧设计写入。

原候选validator不含逐键source coverage及trade_time跨日检查，LLD已明确分钟候选复用完整性helper，提升后原四checks仍执行。四频不是整体事务，原job无固定频率顺序，不承诺一频失败就没有其他频率写入。恢复按原root及逐文件记录，只处理必要部分；正常一次摘要，失败继续所需再校验与重读另计，不自动重跑。

复用已有证据：2025/2026四频共44,224份QFQ、1,654,696,422B，2026子集753,265,659B，22日输出应94,690行。这不是总读取量；原planner键查询、公式计算、候选覆盖、原checks分别计费，正常文件集合粗算已知部分8.268824GiB，另加前序/候选历史/小结果及DuckDB临时读写。需要一次键预检确定候选时再单列开销；没有新增正文读取、性能样本或资源阈值。

21日seed当前身份/质量、因子修复是否满足原LLD的统一正比例缩放条件、候选和fallback历史范围尚待正式前最小确认，不预填fallback=0。后续顺序为设计确认→开发及隔离测试→必要metadata/限定键预检与具体读取批准→原22日job及四checks→唯一receipt/stat收尾。正式提交命令和代码SHA在开发验证后冻结，本轮未生成提交脚本、触发job、运行测试或写正式资源。原两sensor保持STOPPED的最近证据不因本文更新而刷新，23日补齐后启用的TODO保留。

## 48. 分钟九转按LLD开发及隔离验证（2026-10-26）

管理员要求先提交再按LLD落地。原方案、两份原LLD、恢复记录及小型证据按28文件白名单提交`7bbf11cd`，未推送，排除了25MB stat清单、PID及重复临时日志。随后按[原LLD22.9](../../docs/design/dagster-stock-qfq-nineturn-dataset-low-level-design.md#229-代码落地及隔离验证结果2026-10-26)完成分钟专用改动：查询前固定输入、完整候选校验、staging发布、一次摘要、失败留存及同root继续；日线writer、原公式、八列合同、job/check/sensor拓扑、QFQ/MACD默认行为保持。

隔离测试发现并落实两处身份保护：仅nineturn的正式文件被同内容重写也拒绝恢复；候选若在业务audit后被替换，不能生成可供下次误复用的validated记录。这两项先同步原LLD再实现，其他调用的默认行为及receipt内容不变。独立代码复核通过。

四组共189项测试通过：writer41、source-plan14、asset合同/参数转交4、原八文件回归130；另有各组子测试。回归首轮129通过，1项被沙箱拦在未重定向的MACD测试默认临时目录；仅纠正测试隔离参数后单独重跑该例通过，没有修改MACD业务代码或放宽隔离。原公式字面金样本保持，未做性能测试或安装依赖。五源文件/四测试Ruff、文档及差异格式检查通过，CodeGraph已同步。

所有测试使用小人工合同夹具及临时资源；本轮没有运行正式job、读取正式行情或修改sensor。测试Lake/staging/工作目录/脚本已清除，仅留验证记录，正式数据及既有staging删除0。真实seed质量、因子等比例条件、实际历史范围/预算和正式批准仍待后续关闭，清单余4不变。新代码和本节更新尚未提交。证据：[验证汇总及代码SHA](nineturn_write_fix_20261026/summary.json)、[原回归](nineturn_write_fix_20261026/regression-initial.log)、[唯一失败例隔离重跑](nineturn_write_fix_20261026/regression-retry.log)。

## 49. 代码已提交、正式前只读预检（2026-10-26）

本节保留具体读取批准前的阶段记录；当前已完成结果见第50节。

九转修正及189项隔离验证记录已按21路径白名单提交`9d7028af`，未推送。`paths.py`只提交九转旧helper删除，其Raw指数等无关修改仍在工作区。共享暂存区曾被另一任务使用，本轮先撤出自身暂存，待对方提交结束后重建白名单；未混入其他任务。原始回归日志保留原样，三处traceback行尾空格仅作日志格式例外，源码/文档/JSON严格检查。测试时paths.py整文件SHA与本次提交版的区别已记入验证汇总。

执行目标仍为**2026-10-22四频30/60/90/120m九转**。当前只读预检通过：21日四条原检查SUCCEEDED且分别绑定物化storage_id 7712283/7712288/7712292/7712279，来源run均为`24c67557-60a3-4c91-81f7-194f6f677fc1`；精确注册前序为21日。44,224份两年来源的路径/五字段stat与已有清单全部一致，1,654,696,422B；21日四seed共241,384B，22日四目标仍不存在。因子门禁ready、活动run0、pool空闲、两sensor仍STOPPED；补充daemon探测退出码1确认无匹配进程。

隔离解析当前job也通过，仅四资产与四原检查、in-process，未创建run或访问正式资源。初次探测把check业务名误当其op名，按本机Dagster的AssetCheckSpec命名实现校准后通过，未改业务定义。已清除该隔离解析的临时目录和脚本。

尚须按原LLD22.10先确认26股的旧seed是否与当前QFQ一致，再读两年身份键限定实际候选历史。具体年度范围和含收尾/临时预留的估计已单独申请（读16GiB、写3GiB、额外空间3GiB，非运行硬限），尚未收到该项批准。因此**正式job未启动、行情正文读取0、正式写入0、四项仍未补齐**；不能把提交和预检当作补数成功。证据：[当前状态](nineturn_recovery_20261026/status.json)、[metadata预检](nineturn_recovery_20261026/metadata-preflight.json)、[隔离job解析](nineturn_recovery_20261026/definitions-preflight.json)。

## 50. 2026-10-22最后四项九转正式补齐完成

管理员先批准26股历史seed核验、两年四频来源/键预检和原job一次；核验104项seed全部相符。预检实际候选包含`002388.SZ`更早历史，按约定先停在未读范围外文件处；补齐剩余三频已批准键查询后，唯一追加为该代码四频2014—2024的44文件、1.56MiB，管理员另行“确认”。未扩大写入日期、增加代码或资源限制；完整操作顺序记录在[原LLD22.10至22.12](../../docs/design/dagster-stock-qfq-nineturn-dataset-low-level-design.md#2212-正式补齐完成与唯一收尾2026-10-26)。

通过现成`gold_stk_mins_qfq_nineturn_update_job`正常执行一次，run **`2d6cea3f-c4cf-4884-b2a1-1d36dd667159` SUCCESS**，耗时68.843532秒。补数日期精确为**2026-10-22**：

| 数据集频率 | 行数 | 结果 |
| --- | ---: | --- |
| 30分钟九转 | 44,560 | 补齐，原检查通过 |
| 60分钟九转 | 22,280 | 补齐，原检查通过 |
| 90分钟九转 | 16,710 | 补齐，原检查通过 |
| 120分钟九转 | 11,140 | 补齐，原检查通过 |
| 合计 | 94,690 | 四物化、四检查及绑定全部通过 |

四文件共233,592B，每频5,570股票。逐文件候选完整校验后原子提升，receipt/stat对账一致；候选SHA正常一遍、正式文件追加SHA为0。最终只核原run和发布记录/stat，未重算公式/检查、重读年度正文或重做全局审计。8组正常来源、26股历史1,104文件、追加44文件及21/23邻日全部身份不变；两sensor仍STOPPED，无活动run，pool空闲。

按原清单累计恢复**109/109，剩余0**；原136项检查目标销账完成。这不是对新增数据集或23日的新全局审计。23日全部补齐后再启用sensor的TODO继续保留。本次临时脚本/日志已归档并清除，业务staging恢复记录保留，共享`index_daily_p3`目录未误删。代码提交为`9d7028af`，未推送；本节执行证据和文档更新留在工作区供审阅。

证据：[补数汇总](nineturn_recovery_20261026/summary.json)、[四项精确验收](nineturn_recovery_20261026/final-verified.json)、[附加来源/工作目录stat](nineturn_recovery_20261026/final-source-stats.json)、[原job日志](nineturn_recovery_20261026/job-launch.log)、[最终控制状态](nineturn_recovery_20261026/controls-final.json)。
