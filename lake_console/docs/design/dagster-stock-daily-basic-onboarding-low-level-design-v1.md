# 股票每日指标接入 DG 代码级 LLD

状态：P4正式状态补录及最终审计完成；4,056个历史日期已materialized，最近20日40条check通过，待补事件为0。未启用sensor，P5独立推进。更新：2026-09-15。唯一上层目标见[技术方案](dagster-stock-daily-basic-onboarding-plan-v1.md)。历史materialized不等于全历史ready。

## P4实施约束（2026-09-15，已实现，注册结果见§16）

本轮只实现并验证状态发布能力，正式操作先生成只读plan，注册与event写入单独批准。沿用一个`daily_basic_history_cli`，增加`plan-events/register/report-events/audit-events`；不创建新asset/check/job/sensor。新增离线`bootstrap/daily_basic_events.py`承载发布，不被active代码导入。

1. 历史交付使用`delivery_method=prod_history`，metadata冻结`trade_date/file_sha256/source_row_count/code_count/history_plan_fingerprint/history_export_fingerprint/history_audit_fingerprint/source_system=prod_raw_db`。`daily_basic_raw_io.audit_daily_basic_coverage`验证当前文件与该交付身份；仅该方法不读取股票Raw上游，日更`tushare_daily`原校验不变。check/readiness两个消费者同时切换，未知方法不得绕过门禁。active不读取临时报告或历史chunk。
2. 离线plan验证P3 plan/audit/promote完整fingerprint关联、全部正式文件hash与候选证据一致；最近20个日期使用现行两个纯校验器，不重读prod或全历史业务行。校验通过后才构造历史交付metadata，不能拿文件存在伪造绿色状态。
3. 状态查询采用500日期批次和有界分页materialization；check按分区批量取最新索引，完整evaluation只读取最近20日。已有不一致materialization、失败/执行中/失配check、check-only分区或活动本族run均停止，禁止覆盖掩盖。重复执行跳过同一P3证据的现有状态。
4. register只增加候选缺失日期；report-events要求全部候选已注册。每条check明确绑定同一日期当前materialization的storage id/run id/timestamp。支持显式最近窗口sample日期；默认全量materialization而check始终最多40条。部分API失败即停止，重新plan后续补，不能删除已成功event。
5. 只读plan/audit从正式配置解析PG连接，禁自动建表且事务默认READ ONLY；写阶段显式`--apply`、新鲜event plan（最多1小时）与fingerprint，通过Dagster API写入，不使用SQL DML。入口不启停sensor、不创建run、不写Lake/prod、不改共享分区。

性能测算：4,056文件共约0.71GiB哈希读取；仅20日扫描键/schema，不扫描全历史18字段。最多9个日期批次读取check索引，materialization分页每500条、总返回上限20,000条，超限停止而不静默截断；实际已有事件0时为9次空materialization分页查询。最多4,056 materialization+40 check；离线内存仅文件清单与有界事件索引。sensor继续最多10日，无新增全历史读取。无可证明p95的样本，不将一次只读plan计时当SLA。

测试落点：`test_daily_basic_events.py`覆盖P3关联/文件变化、注册幂等、recent20、check绑定、冲突/部分失败、只读零写入；`test_daily_basic_checks.py`覆盖历史无需stock_daily、未知方法拒绝、文件变化失效以及日更回归；已有性能/静态/治理测试保持。完成后原两份文档同步实际结果，正式注册及event不随开发执行。

P3文件基线仍为4,056个交易日、14,288,011行；P4实际验收见§15。

## 1. 审计依据与可复用边界

本次使用 CodeGraph 搜索 `execute_bounded_pages` 并阅读真实实现；同时核对源定义、prod model、source 文档、DG resource、列契约、路径、catalog、cursor 和分区注册参考实现。没有根据历史命名直接复用业务逻辑。

以下路径相对 `lake_console/orchestrator/src/orchestrator/`，除非另有注明：

| 现有代码 | 已核实语义与本期用途 |
|---|---|
| `defs/resources.py` | `TushareResource.call(api_name, params, fields)` 要求显式 fields；复用 `ProdPostgresResource.connect_readonly_transaction()`，不新增 resource |
| `defs/tushare_request_policy.py:execute_bounded_pages` | `request_page(offset)`；短页/空页成功终止；row_key 检测跨页重复；consume_page + retain_rows=False 可避免累计大表 |
| `defs/run_contracts/column_schema.py` | `ColumnContract(name,type,description)` 及 `build_column_schema_metadata`；类型是明确字符串，不接受 unknown |
| `defs/run_contracts/cursor_payloads.py`、`cursors.py` | 使用既有 `build_cursor_details` 与 `build_sensor_cursor`，不修改共享 v1 contract |
| `defs/sensors/cn_a_trade_day_sensor.py` | `build_trade_day_partition_registration_result` 是注册编排入口 |
| `defs/sensors/stk_nineturn_trade_day_sensor.py` | 独立历史起点/分区的调用参考；不能复制其 2023 起点 |
| `defs/catalog/lake_assets.py`、`name_mapping.py` | 新增独立 catalog entry 和名称映射，不改变其它资产 |
| `definitions.py` | 自动加载 defs folder；不新增手写注册总表 |
| 仓库 `src/foundation/datasets/definitions/market_equity.py` | prod daily_basic 的源字段、分页和时间模型证据；禁止作为 DG 运行依赖 |
| 仓库 `src/foundation/models/raw/raw_daily_basic.py` | 18 业务字段、3 系统字段、主键及 Numeric 精度证据 |

源资料与实测报告沿用技术方案 §3。请求分页的实际签名已核验，不使用不存在的通用 writer。后续新增 source/writer 是本族实现，不改共享分页算法。

## 2. 文件级修改清单

| 新增/修改 | 代码位置 | 职责与拟新增符号 |
|---|---|---|
| 新增 | `defs/daily_basic_contract.py` | `DAILY_BASIC_FIELDS`、请求/调度常量、校验结果 dataclass；不存连接配置 |
| 修改 | `defs/run_contracts/asset_column_schemas.py` | `RAW_DAILY_BASIC_SCHEMA`，引用唯一字段顺序 |
| 修改 | `defs/paths.py` | `raw_daily_basic_path(root, trade_date)` 与遵守外置 staging 根的候选 helper |
| 修改 | `defs/partitions.py` | `cn_a_daily_basic_trade_days` |
| 新增 | `defs/source_readiness/daily_basic.py` | `probe_daily_basic_for_trade_date`，日更源探测和最低代码覆盖；不读 prod |
| 新增 | `defs/daily_basic_raw_io.py` | `write_daily_basic_partition`、候选审计、规范化、原子提升；不注册定义 |
| 新增 | `defs/assets/daily_basic.py` | `raw_tushare_daily_basic`，资源编排、stdout 与 materialization |
| 新增 | `defs/checks/daily_basic_checks.py` | 两个 blocking check，不联网重取源数据 |
| 新增 | `defs/asset_guards/daily_basic_readiness.py` | 最多 10 日批量 readiness，匹配当前 materialization/check 身份 |
| 新增 | `defs/jobs/daily_basic_update.py` | `raw_tushare_daily_basic_update_job`，选择 asset + 两个 check |
| 新增 | `defs/sensors/daily_basic_sensor.py` | `raw_tushare_daily_basic_update_job_sensor`，最多一个 run |
| 新增 | `defs/sensors/daily_basic_trade_day_sensor.py` | `daily_basic_trade_day_sensor`，只注册专属日期 |
| 修改 | `defs/run_contracts/configs.py` | `build_raw_daily_basic_update_job_run_config` 与本族配置解析 |
| 修改 | `defs/catalog/lake_assets.py`、`name_mapping.py` | entry、中文名、两条 blocking check、交易日维度；schema 来自常量 |
| 新增 | `defs/prod_db/daily_basic.py` | 18 字段只读 keyset SQL builder，仅 bootstrap 使用 |
| 新增 | `defs/bootstrap/daily_basic_history.py`、`daily_basic_history_cli.py` | 离线分阶段历史导出、转换、对账及显式状态补录；不被 active sensor import |

新增目录如已有同职责本族文件，开发前先复核，避免重复创建。治理映射必须按真实 sensor -> readiness -> check 调用填写，不能仅把 check 名加入白名单。既有 stock_daily 只作为只读输入，绝不修改它的 writer、check 或 sensor。

## 3. 字段、路径与身份合同（R01-R03、R05）

下表为拟定 Parquet schema，已通过 P0 的38,800行源样本及20,000行prod样本转换核验。最大观察小数位4；后续任何超精度值仍须拒绝发布并先修订合同，不静默舍入。

| 顺序 | 字段 | 类型 | 说明 |
|---|---|---|---|
| 1 | ts_code | VARCHAR | 股票代码；非空键 |
| 2 | trade_date | VARCHAR | YYYYMMDD，非空键，对应目录 ISO 日期 |
| 3 | close | DECIMAL(18,4) | 当日收盘价，元 |
| 4 | turnover_rate | DECIMAL(12,4) | 换手率，百分比原值 |
| 5 | turnover_rate_f | DECIMAL(12,4) | 自由流通股换手率，百分比原值 |
| 6 | volume_ratio | DECIMAL(12,4) | 量比 |
| 7 | pe | DECIMAL(18,4) | 市盈率；允许 NULL/负值 |
| 8 | pe_ttm | DECIMAL(18,4) | TTM 市盈率；允许 NULL/负值 |
| 9 | pb | DECIMAL(18,4) | 市净率 |
| 10 | ps | DECIMAL(18,4) | 市销率 |
| 11 | ps_ttm | DECIMAL(18,4) | TTM 市销率 |
| 12 | dv_ratio | DECIMAL(12,4) | 股息率，百分比原值 |
| 13 | dv_ttm | DECIMAL(12,4) | TTM 股息率，百分比原值 |
| 14 | total_share | DECIMAL(20,4) | 总股本，万股 |
| 15 | float_share | DECIMAL(20,4) | 流通股本，万股 |
| 16 | free_share | DECIMAL(20,4) | 自由流通股本，万股 |
| 17 | total_mv | DECIMAL(20,4) | 总市值，万元 |
| 18 | circ_mv | DECIMAL(20,4) | 流通市值，万元 |

除两列键外均允许 NULL。不能将源 NA 转成 0；NaN 缺失表示须显式归一为 NULL，非有限数值或解析失败必须说明原因。prod 数字按 decimal 保留；Tushare 数字转换先验证可无损表达，禁止经 DOUBLE 再转换 prod Decimal。

唯一正式文件：`/Volumes/datasource/data_lake/raw/tushare/daily_basic/trade_date=<ISO>/part-000.parquet`。
唯一候选根：`/Volumes/datasource/data_lake_staging/daily_basic/`。读取按 `hive_partitioning=false`，不从目录推导额外业务列。按 ts_code 排序输出只是稳定布局，不改变值。

Catalog 日更 `source_system` 使用现有 Tushare 枚举；bootstrap materialization 记录实际 prod 来源与方法，不能混写 source_system 单选值。data contract 建议 `tushare_daily_basic_by_date`。不用 prod schema 的 3 个审计字段，也不引入新 SourceSystem 枚举。

## 4. 配置审计（P1/P2值已确认，历史参数另批）

| 配置 | 建议默认值 | 来源/持久化 | 消费者/生效 |
|---|---|---|---|
| page_size | 6000 | 本族 contract 静态常量 | probe/writer，共享字段请求；部署生效 |
| request policy | 最小间隔 1 秒、最多 12 次累计请求、60 秒、网络重试最多 3 次 | 本族构造 `TushareRequestPolicy`，不改共享默认 | probe/writer 单次逻辑调用；重试也占预算 |
| register_start | 17:00 Asia/Shanghai | 本族常量 | 注册 sensor |
| update_start | 19:00 Asia/Shanghai | 本族常量 | 更新 sensor；并非完整性保证 |
| minimum_interval | 900 秒 | sensor 定义 | 更新观察间隔，不是精确调度 SLA |
| continuity window | 10 个交易日 | 本族常量 | readiness/update sensor |
| history_start | 建议 2010-01-04 | 经批准 contract | 注册下限，源最早日期变动不静默修改 |
| write_mode | `write_new`默认，同内容跳过、异内容拒绝；显式`replace`仍完整校验 | 本族 run config | 只有 writer 解析，不新增环境变量 |
| bootstrap 范围/batch_id | plan 显式冻结；无默认截止日 | CLI plan JSON/checkpoint | 离线工具；apply 校验 fingerprint |

不新增 token/连接 env；沿用既有资源。run config 只传目标日期和写入模式，不存代码全集或源响应。调度常量、资产说明、测试从单一合同取值，不复制多个时间字面量。

## 5. 日更代码流程与失败语义（R04、R06-R08、R11）

### 5.1 注册与更新 sensor

注册 sensor 复用 `build_trade_day_partition_registration_result`，输入专属分区、历史下限、17:00，下限前的日期不注册；每 tick 最多 2 日。历史首次注册不靠它逐日慢慢补，由离线计划显式注册。

更新 sensor：

1. 读取 silver 交易日历和专属分区，取最近 10 个实际交易日；注册缺口返回 `missing_registered_partition`。
2. 19:00 前当前日跳过；历史日可在窗口内候选，不引入跨日永久放弃策略。
3. 批量读取本族当前文件及 check 状态。已 materialized 但 check failed 时停住，不覆盖；全部 ready 时结束。
4. 对选中的一个日期核验同日 `raw_tushare_stock_daily` ready，读取其代码集合；不枚举当前 stock_basic 活跃集合。
5. `probe_daily_basic_for_trade_date` 只取该日键字段分页，检查重复/空键/日期和最低代码覆盖。失败不创建 run，下个 tick 可重查。
6. 通过后以 `daily_basic:<ISO>` 作为稳定 run key，调用新 run config helper。已提交/活动 run 不重复提交；失败 run 无自动 attempt 扩号。

source probe的键字段分页已实现。P0七日keys-only响应与18字段请求键集合均一致；既有9月14日分页报告验证offset行为。未来若两种字段请求键集不一致，停止该优化，修订请求方案。

最低代码覆盖的局限与批准门禁严格沿用方案§6：只证明同日行情集合中的股票没漏，不保证所有应有指标代码均已发布，也检测不了两个源同时漏同一代码。P0七日两向差集均为空，已覆盖停牌、新股和退市边界，详见方案§11。管理员已确认采用最低覆盖而不是强制集合相等；额外源代码保留。

### 5.2 writer

`write_daily_basic_partition` 输入日期、写模式、resource 和必要的同日覆盖输入，不允许生产路径由任意用户字符串指定。

1. 检查日期、目标冲突和同日覆盖基线。重新读 ready 输入，不能相信此前 sensor 曾经绿过。
2. `execute_bounded_pages` 使用显式 18 fields、limit/offset、`row_key=(ts_code, trade_date)`；短页/空页终止。分页不完整、重复页、预算耗尽全部失败。
3. 每页以现有列式容器注册到 DuckDB，显式投影 CAST；校验精度再转换。禁止 Python 逐行写 Parquet，拒绝静默去重。
4. 验证源接收行数=候选行数、18 字段规范化值一致、键唯一、日期对齐、最低覆盖通过。多余源代码保留。
5. `COPY` 到外置候选文件，关闭后重读 footer/schema/键汇总；记录候选 SHA-256、输入代码 hash、源行数与方法。
6. 正式提升前再次检查输入未变化和目标未被并发写入；同内容可幂等跳过，不同内容无replace授权则停止。已批准使用本族`fcntl.flock`非阻塞日期锁，位于外置staging固定日期锁目录；锁覆盖目标检查至提升结束，进程退出释放，锁文件不随run删除，不新增共享锁框架。
7. 同卷 `os.replace` 单文件提升。失败删除本 run 未提升候选，不删除或恢复其它文件。资产成功后由现有 Dagster 顺序执行两个 blocking check。

写入前失败不产生成功 materialization。写入成功但 check 失败也不得视为 ready。手动 job 不能绕过 source/覆盖校验。

### 5.3 checks 与 readiness

`file_contract_check` 聚合：文件存在可读、非空、列顺序/type、日期、空键、重复键。输出 `failed_rule_names` 为 list；不拆成多条 check。

`source_coverage_check`聚合：文件fingerprint与本次交付证据匹配、行数/代码数匹配。`tushare_daily`继续要求股票Raw最低覆盖差集为零；`prod_history`核对冻结导出交付身份，不依赖当年并不存在的DG stock_daily状态。当前materialization的交付证据缺失或过期则失败，不借上一run证据；check不重新联网或读取临时报告。仅重跑check时读取该分区最新有效交付；运行中若文件或materialization变化则失败。历史18字段/键全量对账由P3负责，P4发布前逐文件hash确认仍为该版本。

两个 check 均 ERROR/blocking。metadata 记录方法和证据来源，不能使历史分区“按今天股票池通过”。readiness 只接受绑定当前 materialization 的成功 check，并确认文件未变；最多 10 日批量查询，不对全历史逐日扫描 event。

## 6. UI、日志与 cursor（R09）

definition 设置中文说明、18 个带单位的 ColumnContract、正式路径模板、分区维度 trade_date；materialization 不重复塞完整 schema。

`DgStdoutLogger("daily_basic")`本轮实际记录`daily_basic_started`和`daily_basic_completed`，输出日期、交付行数与请求数。交付metadata和check提供中文摘要、下一步与失败规则；执行异常由Dagster保留堆栈。没有逐页刷屏，不打印secret、全表或完整SQL。

运行 metadata：`summary`、`next_action`、`result_status`、行数、代码数、来源、文件指纹、交付方法、输入代码 hash、耗时与 diagnostic_ref，按现有 namespaced helper 写入。较长证据放离线报告，不放 cursor；日更无需新增正式 sidecar 数据集。

cursor 使用现行 builder，`schema_version=1`；details 的 summary/next_action/blocked_component/reason_code/evidence 遵守共享结构。示例人话：

> 9 月 11 日尚未提交：每日指标比同日股票行情少 2 个代码。15 分钟后重新检查源站。

普通 cursor 小于 2KB、硬上限 8KB；最多 3 个代码样本。不调用报告型 `to_cursor_details()`。第一版没有跨 tick repair runtime state，不人为制造状态实体。

## 7. 历史工具与状态发布（R03、R05、R07、R10）

### P3实施约束（2026-09-15批准，代码完成）

最初开发批次只实现`plan/export/build/audit/promote`及隔离测试、有界正式只读plan，未执行正式export/build/promote。后续获批执行范围与实际结果以§14.6—14.7为准；注册、历史交付check分支和事件发布仍属于P4。

配置与输入统一保存在带SHA-256 fingerprint的plan JSON：显式start/end、batch_id、Lake/staging根、交易日历文件hash和日期集合、schema/索引/非执行EXPLAIN证据、P0测算报告hash。SQL批次固定最多10,000行、单线程、statement timeout固定10秒，不增加env配置。CLI生产根固定为正式Lake及外置staging；隔离测试通过纯函数注入临时根。

`plan`只读，不创建Lake/staging目录，不扫描业务行，不生成可提升清单。来源统计沿用标有时点的P0证据；空间与计划估算和实际导出计数分开。执行预算`max_source_rows/max_source_seconds/max_stage_seconds/max_spill_bytes`须在计划中显式冻结，缺失时允许出只读成本报告，但export/build/promote拒绝执行。正式预算待性能报告review后确定，本轮不以默认宽松上限放行。

export以10,000行为持久化unit；每批Parquet完整后再原子更新checkpoint。管理员已确认导出期间指定历史范围不会被prod任务修改，正常执行只做一遍顺序读取，不做第二遍全量来源重核。中断续跑从源范围开头重新比较已持久批次，再续出；已完成批次重复执行仅校验本地chunk，不读prod业务行。只保存计数/hash/主键和文件身份，不保存全历史Python列表。来源稳定是本次运营前提，不是工具证明的数据库一致性快照。

plan与完成checkpoint固定记录`source_policy=operator_confirmed_stable_single_pass`，不是env或可切换配置项；由本族工具生成并纳入fingerprint，所有P3阶段通过`_validate_plan`校验，缺失/不同策略的旧plan拒绝执行。日更消费者不读取该字段。若窗口不能继续保证来源不变，停止并重新评审，不自动恢复两遍模式。

build一次将chunk分流至年度staging，再按年聚合写日期分区，正式字段仍为18列。复用DuckDB连接设置，spill改在本batch外置staging下，按冻结预算限额；不修改共享默认值。audit按年做18字段双向差集、schema/键/日期核验及按日聚合，不能对每个日期重复扫描全年。promote复用日更的`daily_basic/locks/<date>.lock`，核对当前候选hash与报告、目标内容和同卷后逐文件原子提升。保留候选用于中断重核；无备份或Kopia，幂等续跑不能覆盖异内容目标。

硬口径测试映射：SQL字段/原生DATE/keyset/timeout由prod source测试锁定；批次损坏、来源增删改、续跑由history export测试锁定；按年构建/18字段/日历差集由build/audit测试锁定；预算缺失、stale报告、锁竞争、同内容幂等、异内容拒绝及提升中断由promote测试锁定。active定义和日更check/readiness保持不变。

容量样本预先测算：P0年度日历最多245日，近期源最大5,550代码；用245×6,000=1,470,000行合成年度压力包络，147个10,000行chunk、245个按日文件。不是prod实际最大年度。按P0字节系数估算chunk约44–46MB、按日候选约77MB、年度中间约44–46MB，正式增量另约77MB；spill和进程内存单独记录，不拿压缩文件大小当内存。隔离样本source checkpoint由DuckDB生成，不消耗prod查询；另用10,000行分页用例验证Python批次上界。审计对冻结chunk一次读取进入受限DuckDB临时关系，再按年核对；只读audit关闭spill，内存不足即停止。构建允许在本batch staging的spill配额内执行。未完成unit保留在独立attempt目录，续跑重用已冻结年度/年份清单，重新生成未完成unit，不自动删除异常现场。

245日期容量样本发现DuckDB分区写入可能因打开文件数限制而为同日生成多个片段。年度分流后，仅对该日期片段执行一次set-based合并和按code排序，形成`part-000.parquet`；不逐日扫描全年。片段保留为staging执行证据，不提升；空间估算额外计入最多一份日期候选体量。正式文件始终每日期一个，不通过提高共享线程/打开文件默认值绕过验收。

### 7.1 显式 SQL 与导出版本

`defs/prod_db/daily_basic.py` 仅允许 `raw_tushare.daily_basic` 的 18 列。参数绑定的 keyset 模板如下，首批省略 last-key 条件：

```sql
SELECT ts_code, to_char(trade_date, 'YYYYMMDD') AS trade_date,
       close, turnover_rate, turnover_rate_f, volume_ratio,
       pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm,
       total_share, float_share, free_share, total_mv, circ_mv
FROM raw_tushare.daily_basic
WHERE trade_date >= %(start_date)s AND trade_date <= %(end_date)s
  AND (ts_code, trade_date) > (%(last_code)s, %(last_date)s)
ORDER BY daily_basic.ts_code, daily_basic.trade_date
LIMIT %(batch_size)s
```

WHERE日期使用原生DATE参数，last_date也是DATE；ORDER BY显式限定原表列，不使用SELECT的字符串别名。每批独立READ ONLY事务、statement timeout；不长持全历史事务，不用OFFSET翻历史、不按日期重扫。准入要求EXPLAIN走索引且无Sort/Incremental Sort/Seq Scan，不能仅凭出现索引节点就认定通过。

每批写完整 candidate chunk 后原子冻结 checkpoint：batch_id、范围、last_key、行数、内容 hash、文件、完成时间。最多 10,000 行常驻，DuckDB 内存/线程和 spill 采用本工程资源限制。中断仅保留完整 chunk；源导出阶段重启必须重核已有 chunk，不允许只凭 last_key 忽略源补写到较小键的记录。

正常完成不重拉来源。仅中断续跑时重新遍历已持久前缀，比较键/值/批次边界，变化即停止；完成后的版本以本地chunk为准。保留导出前后schema核验，但不能由schema不变推断业务值不变。不得声称单遍工具能识别已读取范围后续发生的全部增删改；本次依赖管理员确认的稳定窗口，不擅自开长期事务。

### 7.2 CLI 阶段

| 阶段 | 可执行动作 | 不允许 |
|---|---|---|
| plan | 有界只读成本、源schema/索引、日历候选/目标冲突审计，实际源日期/行数尚不冻结；报告 /private/tmp | Lake/事件写入、全历史扫描 |
| export --apply | 获批后导出到外置 staging、checkpoint、冻结版本 | 正式提升、事件写入 |
| build --apply | 从冻结 chunk 用 DuckDB 转按日候选，按年批次；一次逻辑读取而非每日重扫全部 chunk | 直接覆盖目标 |
| audit | 源导出与候选全 18 字段双向 EXCEPT ALL、行数、键、日期/schema、空间/冲突 | 将 check 状态当数据事实 |
| promote --apply | 新鲜审计后逐文件原子提升、checkpoint | 多文件整体原子承诺、Kopia |
| plan-events / audit-events | 当前P3文件及DG状态只读对账，冻结待注册/待补事件清单 | 写任何正式状态 |
| register --apply | 仅注册已批准候选日历集合到专属分区 | 删除共享分区 |
| report-events --apply | 全部已核实文件可补 materialization；只给最近 20 个实际交易日补两个 check；可显式sample-date | 历史全量 checks、job/run |

以上均在同一个CLI实现，不增加Dagster asset/job。技术方案中的build包括候选生成与独立提升批准；拆开执行动作，防止生成候选就意外发布。P4写阶段额外提供`--event-plan`及其fingerprint（不是P3 plan fingerprint），register后重做plan，再审批report-events；audit-events重算剩余清单，未全部完成时不会自称全量ready。

采用 chunk 一次分流到年度 staging、再逐年按 trade_date 聚合 COPY 的方式；禁止每年反复从 prod 拉相同数据。年度内多 chunk 最终合并为每个交易日一个正式文件，不留下 chunk 作为正式 Lake 数据集。

计划冻结：范围、交易日数、source row/distinct pair、年度行数、导出版本 hash、预计文件/event 数、磁盘和成本上限。交易日来源为正式交易日历；源日期不在日历、重复键或空日期都停止解释，不静默丢弃。

check 写入必须绑定本轮/当前正确 materialization；事件 apply 要显式批准和新鲜 plan。重复执行跳过一致事实；已有冲突 check/materialization 不删除，不再补一条绿状态掩盖它。N 个目标日最多 N 条新 materialization + min(N,20)×2 条 check；当天日更事件另计，不能混进 bootstrap 配额。

## 8. 性能计划与停止线（R11）

| 路径 | 工作量/上界 | 准入要求 |
|---|---|---|
| sensor 稳态 | 最多 10 日文件状态和批量事件；无 prod 读取 | 不随全历史增长 |
| sensor 选中日 | 一次 keys-only 分页；P0七日均1页 | 主样本约0.07-0.10秒；不是完整tick实测，目标仍<10秒 |
| writer | 一次完整 18 列分页、同日候选校验 | 当前样本应 1 页，未来满页继续；每次调用最多 12 请求/60 秒 |
| 日更合计 | probe + writer 各独立调用，最多 24 次/120 秒累计等待上界 | 正常样本 2 个请求；不宣称 1 请求或已验证 p95 |
| 历史 export | 10,000 行/批，样本总量约 1,429 非空批次+终止页 | 实际总数由单遍导出累计；不额外全表COUNT或完整重核，中断前缀读取另计 |
| 历史 build | staging 分流 + 年度聚合；18 字段列式处理 | 按最大年度测内存/spill/文件字节；不能直接全量试跑 |
| 事件 | N materializations、最多 40 checks | 不全历史 readiness 深扫 |

P0 有界性能取样建议最多 3 个主键位置，每次最多 10,000 行、statement timeout 10 秒；总共不超过 30,000 行，单线程。它只给导出风险证据，不冒充完整 source baseline。超时/IO 放大严重就暂停，不能自动增加 timeout 或全扫。

全量 plan/apply 前必须填实：磁盘需求=导出chunk+年度候选+日期碎片+最终候选+正式增量+spill余量，及单遍导出/本地对账/构建总耗时和prod可接受IO。P0已补有限样本的传输/压缩字节，但不能以样本估算代替P3全量性能门禁。

### 8.1 P0 实测与准入判断

完整事实见技术方案§11和 `/private/tmp/daily_basic_p0_20260915_070936/`，不另建设计文档。关键执行限制与结果：

1. 源调用15次（14 SDK + 1 MCP），无重试，少于30次预算；七日期38,800行，schema、键、日期、精度、全字段读回差异均通过。
2. prod两个主键位置非执行EXPLAIN均Index Scan。第一位置另执行一次10,000行EXPLAIN ANALYZE，耗时2.96秒，读取79.3MiB页面；两个实际导出各10,000行、约1.33/4.95秒。合计执行预算30,000行、导出20,000行，没有额外全历史COUNT或第三位置取样。
3. prod取样通过18字段Decimal转换和双向读回，但存在heap IO放大。第一批导出缓存被分析查询预热，第二批未测实际buffer，不把两批平均值当SLA，也不继续放大取样。
4. 按9月14日14,288,011行估计约1,429非空批次+终止页；导出一次约31.6-117.8分钟。P0原两遍测算63.2-235.6分钟是历史方案，现行已取消第二遍。JSON仅为审计传输，不强制成为未来exporter协议。
5. 审计JSON单遍估计4.81-4.83GiB，chunk约0.40-0.42GiB，按日正式文件约0.70GiB；年度中间文件另留约0.40-0.42GiB。累计基础文件约1.50-1.54GiB，不含spill、元数据和安全余量。不能声称它就是最大空间需求；年度排序时间/内存峰值尚未测。
6. 日历候选4,056，范围2010-01-04至2026-09-14；这是P0建议范围，不是生产硬编码，实际prod日期覆盖仍由P3冻结。目标目录不存在，无覆盖冲突；候选状态最多4,056+40条。

P0已为P1/P2日更源与类型设计提供技术样本依据；口径随后获确认并进入编码。P3的keyset实现不因此获准全量执行：先解决IO/重核成本和来源稳定策略，不新增索引或长事务绕过。P0未发生Lake/DB/event写入或任何sensor/job操作。

## 9. 测试落点与开发顺序

测试均位于`lake_console/orchestrator/tests/`。日更、P3历史文件和P4事件工具测试均已实现；最新结果见§15：

| 文件 | 必须覆盖的正反例 |
|---|---|
| test_daily_basic_contracts.py | 18 列/顺序/单位/两键；禁止内部字段与 limit_status；日期转换、NULL、超精度/溢出拒绝 |
| test_daily_basic_source_readiness.py | 短页/空页/满页续页、重复页、异常重试预算；缺必需代码失败、额外代码保留；空日失败 |
| test_daily_basic_raw_io.py | fixture 列式写、全字段一致、失败不覆盖、目标冲突、并发保护、精度失败、重复 apply |
| test_daily_basic_checks.py | 两个 check 所有规则、交付证据缺失/文件变化失败、历史不按当前池；failed_rule_names 为 list |
| test_daily_basic_sensor.py | 19:00 前不请求、同日输入缺失/失败不请求、缺注册日期、每 tick 一 run、稳定 run key、源不齐重查、失败 run 不自动改 key |
| test_daily_basic_sensor.py（注册部分） | 下限、开市日、最多两日注册、不提交RunRequest、默认STOPPED；复用实际注册helper及临时交易日历 |
| test_daily_basic_history.py | plan 零写、keyset 参数、checkpoint 损坏/源增删改拒绝、跨批重复、schema/值差异；中断续跑和原子提升 |
| test_daily_basic_events.py | materialization 可全量但 check recent20、目标绑定、幂等、缺分区/冲突拒绝、materialized 不等于 ready |
| test_daily_basic_performance.py | 已验证10日固定文件和查询工作量；source请求上限在source_readiness用例保护。bootstrap内存门禁留P3，不宣称已验证 |

更新现有 `test_run_contract_configs`、`test_sensor_cursor_contracts`、`test_asset_governance_contracts`、`test_asset_check_incremental_governance`、`test_run_contract_static_gates`：确认新对象实际消费链、source/partition/path/schema 一致，禁止 active -> bootstrap/prod history、报告型 cursor、SELECT *、逐行写 Parquet、全历史 check。

实施顺序与方案一致：P0口径/成本准入 -> P1纯合同与IO -> P2 active编排/治理 -> P3离线历史工具 -> P4状态发布 -> P5真实日更。每阶段测试通过才更新状态；本次使用现有`.venv/bin/python -B -m pytest`及受保护治理测试启动器，不安装依赖、不自动同步环境。

正式验证另批准：definitions 加载、历史导出/提升、动态分区、runless events、最小日更 run、启用 sensor。测试使用临时 fixture/ephemeral instance，绝不连接正式资源执行写入测试。

## 10. 方案一致性审计与未完成门禁

| 约束 | LLD 落点 | 验证证据/开发验收 |
|---|---|---|
| R01 | §3 schema、§7 SQL | contracts/静态字段反例 |
| R02 | §3、§5.2 | NULL/负值/超精度和全字段 IO 测试 |
| R03 | §2 source 与 prod 模块隔离 | active import 门禁 |
| R04 | §4、§5.2 | 分页/预算/重复页测试；已有分页样本 |
| R05 | §3、§7 | 注册与 migration 日期差集 |
| R06 | §5.1 | P0七日代码差集与边界样本通过；局限及业务口径仍需确认 |
| R07 | §5.2、§7.2 | 失败不覆盖/并发/续跑测试 |
| R08 | §5.3 | 两个聚合 check 与版本身份测试 |
| R09 | §6 | 中文摘要、长度、schema definition、日志禁密测试 |
| R10 | §7.2 | N+min(N,20)×2 事件计数/绑定测试 |
| R11 | §8 | 已执行30,000行业务预算内取样；存在IO放大，完整历史性能未放行 |
| R12 | §2、§9 | scoped diff、默认 STOPPED、生产审批隔离 |

设计审计结论：两份文档目标均为股票daily_basic的18字段Raw接入；来源、路径、分区、check、状态数量和阶段批准一致。P1/P2实现结果见13节，P3历史文件工具见14节；P4代码与只读plan见15节，正式状态写入未执行。

P0后结论：完整日数值精度、keys-only及最低覆盖边界样本已验证。对象、时间、Raw-only、最低覆盖局限及P1/P2实施已获确认；只允许代码与隔离测试。历史建议截止为2026-09-14，P3仍需冻结实际源日期/行数、独立事务来源稳定策略及可接受成本；历史全量执行明确不放行。

### P1/P2执行约束补充

- 先纯contract/source/writer/校验器测试通过，再接asset/check/job/sensor/catalog/readiness。
- 只实现日更交付证据，不提前实现prod/bootstrap历史证据分支；没有历史基线时限定最近10日，不扩大至2010年。
- 现有共享resource/分页默认值保持不变；若必须改共享接口或预算无法满足，停止并说明，不擅自绕行。
- source/code、文件指纹和materialization/check身份同时验证；当前run不得误用其它run的交付证据。
- 不运行正式源/DB/Lake测试，不安装依赖；definitions加载与正式任务另批。完成后标为代码完成、待正式验收，不自动进入P3或启用sensor。

### P1复用审计与已批准修订：60秒预算（2026-09-15）

P0及确认口径已提交`ad0ff5b3`。以下是编码前暂停的审计证据；管理员已批准局部修订并恢复P1/P2。

当前`_BoundedRequestRunner.execute`仅在发请求/等待/重试前检查剩余时间；成功响应返回后直接返回success。`execute_bounded_pages`遇短页结束时不补查时间。隔离假时钟复现：预算60秒，单次请求在第61秒返回短页，结果为`completed=True, elapsed_ms=61000, budget_exceeded=False`。没有真实网络调用，也没有等待61秒。

`TushareResource.call`复用SDK默认30秒网络timeout，没有传递本次剩余额度的接口；网络timeout不等于整个分页调用的硬墙钟截止。不能仅配置`max_elapsed_seconds=60`就宣称超时结果一定被拒绝或进程一定在60秒内返回。

CodeGraph的search/callers/impact与源码核对确认共享分页器还被指数增强因子、DC、全球指数、ETF日线消费。本轮不修改共享实现，已确认以下口径：

- 60秒作为本族成功结果的接收截止。已新增本族请求返回后、页面消费前及最终返回前的elapsed检查，超额直接失败，不提升文件、不提交run；不改变共享接口。
- 该方案不能强行中断在途同步HTTP请求，实际错误返回可能晚于60秒。若必须保证整个调用60秒内结束，需要另行设计请求级deadline/取消及资源接口，不能本轮临时扩散修改。

上述已落入`source_readiness/daily_basic.py:fetch_daily_basic_pages`，由假时钟的迟到响应、消费后超时、累计请求及网络重试用例保护。没有扩大12次/60秒预算，没有修改共享SDK timeout。

## 13. P1/P2代码级交付对账（2026-09-15）

路径相对`lake_console/orchestrator/`。以下表格仅列P1/P2实际实现，P3工具另见14节。

| 已确认硬口径 | 实现位置/符号 | 本地验证 |
| --- | --- | --- |
| 18字段、精度、单位和历史下限唯一 | `defs/daily_basic_contract.py`、`run_contracts/asset_column_schemas.py:RAW_DAILY_BASIC_SCHEMA` | `test_daily_basic_contracts`锁字段顺序和DECIMAL；raw_io测NULL/负值、超精度和溢出拒绝、2010年前拒绝 |
| 日更只读Tushare、额外代码保留 | `source_readiness/daily_basic.py:fetch_daily_basic_pages/probe_daily_basic_for_trade_date` | keys-only最低覆盖、重复/空键/错日/字段缺失拒绝、额外代码保留 |
| 6000行页、1秒间隔、12次/60秒累计预算 | 同上，复用共享`execute_bounded_pages`，本族guard补返回后/消费前/最终截止 | 6001行分页、重试计入12次、间隔、61秒迟到响应不消费、消费后超时不成功 |
| 安全单文件写入、显式replace | `daily_basic_raw_io.py:write_daily_basic_partition`、`paths.py` | 全18字段读回、同内容幂等、冲突拒绝、提升异常保留原文件、候选清理、上游变化拒绝、锁忙拒绝和子进程退出释放 |
| 同日Raw日线为最低覆盖 | `asset_guards/daily_basic_readiness.py:load_daily_basic_input_codes` | 先核ready；实际上游文件不存在、字段/日期/空键/重复键异常均拒绝；按日代码聚合读取，不用当前股票池过滤历史 |
| 2个聚合check，无历史证据兜底 | `checks/daily_basic_checks.py:daily_basic_check_result` | 缺证据或文件变化红；当前run不能借其它run交付；单独重跑check可使用最新有效交付；failed_rule_names为list |
| Materialized不等于ready | `asset_guards/daily_basic_readiness.py:batch_daily_basic_readiness` | ephemeral instance验证无check不ready、旧check绑定新materialization不ready、文件变化不ready |
| 最近10日、有界状态读取 | 同上；materialization一次最多100条；每日期一次批取两个check（至多10批） | 超过10日拒绝；查询截断不扩大扫描；10文件fixture记录查询数与耗时 |
| Raw-only、job不执行上游 | `assets/daily_basic.py`、`jobs/daily_basic_update.py` | 隔离Definitions解析验证专属分区、IdentityPartitionMapping、selection只有本asset与两check；隔离job完整执行全绿 |
| 17:00注册、19:00更新、15分钟一次、最多1run | 两个`daily_basic*_sensor.py`，配置常量只取contract | 真实临时交易日历验证日期下限/开市日/每次至多2日期；更新测试时段、历史窗口、注册缺口、源不足、上游失败及既有run不自动重试 |
| v1短中文cursor，无报告型详情 | 两个sensor；注册helper返回的调度请求保持原样，仅本族替换summary/next_action中文 | 普通更新cursor小于2KB；静态禁止报告型`to_cursor_details`；注册/更新均默认STOPPED |
| catalog和真实readiness/check映射同步 | `catalog/lake_assets.py`、`name_mapping.py`、`partitions.py`、`run_contracts/configs.py`及治理测试 | 新partition model、新source字段schema、新sensor定义ID；两check参与真实sensor readiness，未凭猜测填映射 |

### 13.1 验证结果与证据

从orchestrator现有`.venv`运行，未安装或更新依赖：

```bash
.venv/bin/python -B -m pytest -q tests/test_daily_basic_contracts.py tests/test_daily_basic_raw_io.py tests/test_daily_basic_checks.py tests/test_daily_basic_source_readiness.py tests/test_daily_basic_sensor.py tests/test_daily_basic_performance.py tests/test_run_contract_static_gates.py tests/test_run_contract_configs.py tests/test_sensor_cursor_contracts.py tests/test_tushare_request_policy.py tests/test_asset_check_incremental_governance.py
.venv/bin/python -B tests/stock_suspend_confirmed_test_runner.py --scope regression --suite test_asset_governance_contracts.py
```

- 第一组202项通过、166个子用例通过，约8.48秒。报告`/private/tmp/daily_basic_p1_p2_tests.log`。
- 受保护catalog验证12项通过；报告`/private/tmp/daily_basic_p2_protected_governance.log`。首次普通入口失败是受保护support未加载；随后按其固定启动器执行。固定源码白名单仅补本次新增模块的精确路径，未开放目录通配、网络或正式文件，未减少断言。
- 全仓Ruff致命错误门禁通过；所有本次新代码默认规则通过。共享`configs.py`默认规则仍报11条已有DTZ007/TRY004，已对照`git show HEAD:.../configs.py`确认原样存在，不修改历史行为以消除告警。
- 10日fixture共10,000行，10个输出文件、一次本asset materialization查询、10次两check批次核对，约0.029秒。实例查询和上游代码在该计时用例中为替身；实际源文件和DuckDB核验在临时目录执行。这只证明固定工作量和本地文件成本，不是正式DB/网络p95。
- 上述开发验证阶段未执行`dg check defs`、正式instance读取/执行、真实Tushare/prod日更、正式分区注册和历史导入。后续独立批准的definitions与只读验收见13.2；ephemeral job/check/event及临时Parquet不属于正式状态。

### 13.2 后续准入

P1/P2代码已提交`bb903dbe`（本专项27文件），之后经管理员批准完成以下验收：

| 门禁 | 实际结果 |
| --- | --- |
| Definitions | 现有`.venv/bin/dg check defs --use-active-venv`成功；`DAGSTER_HOME=/private/tmp/daily_basic_acceptance_LlLBlC/defs_home`，禁止依赖同步与下载 |
| 正式只读状态 | PostgreSQL连接强制默认只读及10秒statement timeout，storage设置`should_autocreate_tables=False`，未初始化正式instance；新专属分区0，本族sensor持久state0，正式目标目录不存在 |
| 同日上游 | `load_daily_basic_input_codes`验证2026-09-14股票Raw readiness及实际文件，5,550代码，hash为`e724ed3ff15cb4f48f084d227026882699e7f88cf1059ec28415e32c10642003` |
| 源覆盖 | `probe_daily_basic_for_trade_date`仅取`ts_code,trade_date`，5,550代码，missing=0、extra=0，1次请求，202.684毫秒；没有执行sensor evaluation |
| 未生产状态 | 新asset当日`missing_materialization`，正确保持非ready；没有伪造绿色check或交付证据 |

证据：`/private/tmp/daily_basic_acceptance_LlLBlC/definitions.log`、`readonly_audit.json`及可复核的`audit.py`。正式只读样本通过不等于所有日期或正式写入验收通过，单次源耗时不作为p95。验收未访问prod业务库、未注册日期、未提交run、未启停sensor、未写正式Lake/DB。

P2验收时尚未创建prod导出、history/bootstrap或runless发布入口，未发生正式写入；后续P3工具结果见14节。只读通过不构成历史写入授权，实际源日期/行数与执行预算仍须后续冻结。

上述13节是P2验收时点记录。随后批准的P3实现与验收以本节为准。

## 14. P3代码、测试与只读Plan结果

P2验收文档提交`c134f056`；P3新增代码不改变共享接口、active依赖或日更行为。CodeGraph搜索及callers确认`write_daily_basic_partition`由Raw asset和本族测试调用；本阶段仅离线单向依赖本族精度校验与路径，不让active链路导入历史模块。

| 职责 | 当前实现 | 验证与边界 |
| --- | --- | --- |
| 18字段keyset与只读身份检查 | `defs/prod_db/daily_basic.py` | 原生DATE参数，10,000行fetchmany，10秒statement timeout；SQL无OFFSET/通配字段；inspect仅catalog与非执行EXPLAIN |
| 成本plan、checkpoint、来源冻结 | `defs/bootstrap/daily_basic_history.py` | plan缺预算只能出报告；固定单遍策略，源schema前后核验，中断续跑前缀校验；损坏、前缀变化、预算耗尽停止 |
| 年度构建与18字段对账 | 同上 | 一次chunk分流，日期局部碎片合并；audit按日期有序临时关系与年度范围谓词核对，保留zone-map裁剪条件；按文件核对日期，不能只对全年度总数 |
| 原子提升与续跑 | 同上 | 当前日更日期锁、同内容异编码也可跳过；目标冲突、候选变化、跨卷拒绝。保留候选，复制本日期提升临时文件并核hash后os.replace；不是旧文件备份 |
| 操作入口与误用防护 | `defs/bootstrap/daily_basic_history_cli.py` | 五阶段；写阶段显式apply+plan fingerprint，正式根/挂载校验，报告仅/private/tmp且不能覆盖输入计划；不调用DG状态写入API |
| 自动回归 | `tests/test_daily_basic_history.py` | 37项：包含单遍请求数、完成后零业务重读、旧plan拒绝、单遍成本、10,002行跨批、中断前缀增删改、精度/键/日期、checkpoint、候选内容、同内容异编码、锁冲突、提升中断/跨卷、碎片合并及active无历史依赖 |

执行预算来自plan，CLI无宽松默认值。`max_source_rows`限制单遍范围行数，`max_source_seconds`限制同次导出含中断前缀校验的累计耗时；`max_stage_seconds`在构建/审计/提升的unit边界检查，不宣称强制中断正在执行的DuckDB语句。`max_spill_bytes`约束本batch构建spill；只读audit禁spill，内存不足停止。均不修改共享resource默认配置；批次源记录最多10,000行，规范化和DataFrame副本同属该批次，不累计全历史Python数据。

### 14.1 本地验证

- 历史35项与P1/P2/静态/配置/请求策略回归合计237项、166个子用例通过；`/private/tmp/daily_basic_p3_tests.log`。受保护catalog单独12项通过，`/private/tmp/daily_basic_p3_protected_governance.log`。
- 本次四个Python文件默认Ruff及全仓致命错误门禁通过；原有共享`configs.py`告警没有扩散修改。文档完整性与`git diff --check`通过。
- 容量最终报告`/private/tmp/daily_basic_capacity_txpfb54k/performance.json`：147万行、147个chunk、245个目标候选；构建1.916秒、audit1.445秒，峰值RSS1,947,877,376字节，chunk79,135,218字节、最终候选79,967,926字节。仅临时合成数据，source查询0、正式写入0。
- 容量验证先发现测试生成SQL的多参数COPY不受当前DuckDB支持，仅调整临时fixture生成写法；又发现多日期COPY产生碎片，已按本族日期局部合并修正并增加回归。未改共享DuckDB设置、未安装依赖。
- spill残留0不是峰值；真实全历史audit排序内存与文件提升成本尚未实测。147万行测试不能替代14,288,011旧统计对应的全量验证。

### 14.2 正式只读Plan与后续批准

通过根目录规定的`bash scripts/psql-remote.sh -f ... -- -A -t -q`执行`DailyBasicHistorySource.inspect`生成的同一组SQL。事务为READ ONLY、每SQL10秒timeout；只读18字段的schema/精度、主键/索引及两条非执行EXPLAIN，实际新增业务行读取0。正式日历只读，结果4,056个候选、目标冲突0、可用空间2,945,511,534,592字节。

原两遍成本plan：`/private/tmp/daily_basic_p3_plan_gfmd64o4/plan_with_capacity.json`，fingerprint=`f4fbf97ec2064d0c7de6079895a895596db29971efa7c9299b87d93a0bb748c6`，保留为历史只读证据。当前单遍策略不接受该旧plan，须重生fingerprint；预算未冻结、实际source日期/行数为空时，仍不能进入export/build/promote。

单遍来源导出按P0估算31.6—117.8分钟，第二遍来源读取为0；10,000行本地规范化/Parquet读回0.398秒，单遍外推约9.5分钟。两者不是全量实测，也不能无条件相加。基础文件约2.93GiB，包含chunk、年度中间、日期碎片、最终候选及正式增量，另计spill与中断attempt；执行前按冻结max_source_rows同比调整空间预检。`history_cost_estimate`输出`source_pass_count=1/export_minutes/source_recheck_minutes=0`，删除旧合计字段；调用方仅CLI及本族测试，无active消费者。

当前结论：**P3工具与只读计划完成，待全量执行评审**。先review成本和冻结`max_source_rows/max_source_seconds/max_stage_seconds/max_spill_bytes`，再单独批准源端窗口与sample/batch；本轮未执行正式export/build/promote、DG分区/事件写入或sensor/job操作。P4注册、materialization与recent-20 check发布仍待后续设计落地。

### 14.4 单遍修订验收

- 管理员确认来源稳定后，仅修改`daily_basic_history.py`、对应测试和原两份文档；CodeGraph `query export_daily_basic_history`及代码引用审计确认消费者为本族离线CLI/测试，无active资产或sensor依赖。
- 新成本报告`/private/tmp/daily_basic_p3_plan_gfmd64o4/plan_single_pass.json`，fingerprint=`0962516dbeb6ed93ac7e2a9ac40d888fd215a15a51fbd8bb70b787d155ab8032`。只复用原只读证据重新计算单遍成本与策略身份，新增prod业务查询0；不代表源端事实已重新观测。预算仍未冻结。
- `test_single_pass_and_completed_export_does_not_reread`锁定正常导出仅一遍、完成后不重拉；10,002行跨批测试只允许3次请求（两页数据及终止页），不再是6次。中断前缀增删改、chunk损坏、候选对账、精度与安全提升测试保留。
- `test_old_plan_policy_is_rejected_before_source_read`拒绝缺单遍策略的旧plan；`test_cost_estimate_only_budgets_one_source_pass`锁定单遍成本、不保留旧合计字段。
- 239项定向/回归测试及166项subtests通过，含37项历史工具测试；日志`/private/tmp/daily_basic_p3_single_pass_tests.log`。Ruff通过。未执行正式导出/提升、日期注册、事件或sensor/job操作；未自动提交本次修订。

### 14.5 执行前排序漏项与最小修正计划（历史停止记录，已按§14.6修正）

单遍修改已提交`87f7ece0`。管理员明确DG及其离线工具用标准`ProdPostgresResource`，无需套用非DG的命令脚本入口。2026-09-15新鲜plan报告`/private/tmp/daily_basic_p3_current_plan_20260915_101753.json`：4056候选、目标冲突0、业务行读取0，但两处EXPLAIN包含`Incremental Sort`。当前空stop列表是性能门禁漏报，不能用于执行。

根因及修正范围：

1. `defs/prod_db/daily_basic.py::daily_basic_history_query`的输出别名`trade_date`遮蔽原列，`ORDER BY ts_code, trade_date`排序的是格式化字符串，未完全沿用主键顺序。拟仅改排序为`ORDER BY daily_basic.ts_code, daily_basic.trade_date`，其余18字段、日期过滤、keyset、批次上限和类型保持不变。
2. `defs/bootstrap/daily_basic_history.py::make_history_plan`通过序列化文本精确查`"Sort"`，没有覆盖`"Incremental Sort"`。拟按JSON节点结构递归检查`Node Type`，保留索引与顺序扫描门禁，并拒绝两类排序。
3. `tests/test_daily_basic_history.py`补充首批/续页SQL原列排序断言，普通Sort、Incremental Sort和嵌套Seq Scan拒绝、直接Index Scan通过的测试，避免仅因树中存在索引节点就误判通过。
4. 隔离测试通过后再运行相同只读plan；两处都应为`Limit -> Index Scan`，成本预算仍需冻结，不因SQL修正自动提升文件。

已完成纯只读对比（不是代码修改）：`/private/tmp/daily_basic_ordering_explain_20260915.json`，使用相同标准resource、相同参数，仅将ORDER BY限定原表列，两处增量排序消失。没有ANALYZE或业务取样，未获得新的耗时实测。按“发现计划与实现冲突先停止”的规则，本轮未修改生产代码，未执行全量导出或写湖。

### 14.6 获准修正后执行记录

管理员随后批准“修正，然后继续推进”。已将ORDER BY限定原表列，并递归读取EXPLAIN的`Node Type`，拒绝Sort、Incremental Sort、Seq Scan；新增首批/续页及嵌套节点回归。245项测试通过，日志`/private/tmp/daily_basic_p3_ordering_tests.log`，Ruff通过。

本次执行限于2010-01-04至2026-09-14的外置staging导出、按日构建和本地审计；正式promote、注册及事件另行收口。batch_id=`daily_basic_20100104_20260914_20260915_102124`，工作区`/Volumes/datasource/data_lake_staging/daily_basic_history/daily_basic_20100104_20260914_20260915_102124`。资源仍为既有ProdPostgresResource，读取18字段、单线程主键分页，源端不写入。

执行预算显式写入本轮plan：`max_source_rows=15000000`（高于14,288,011旧统计约5%，实际数从导出累计）、`max_source_seconds=10800`（P0单遍最慢估算约118分钟，加本地处理/连接余量；3小时是停止线）、`max_stage_seconds=1800`、`max_spill_bytes=4294967296`。DuckDB仍为既有16GiB/4线程，audit禁spill。基础文件按上限缩放加spill约7.1GiB，移动盘当前约2.7TiB可用。超限停止，不自动扩容或追加预算；不把上限当实测耗时。

### 14.7 Staging执行验收（2026-09-15完成）

| 阶段 | 实际结果 | 报告 |
|---|---|---|
| 新鲜plan | 两处均Limit→Index Scan，无排序/顺序扫描；4,056个日历候选，目标冲突0，显式预算已冻结 | `/private/tmp/daily_basic_p3_execution_plan_20260915_102124.json` |
| 单遍export | 14,288,011行，1,429个非空chunk加终止页；完成冻结，2,427.37秒（40分27秒），schema前后相同 | `/private/tmp/daily_basic_p3_export_20260915_102124.json` |
| 年度build | 17年、4,056个按日候选、14,288,011行；日期集合等于日历；日志创建至末次输出约20.7秒，非独立函数计时 | `/private/tmp/daily_basic_p3_build_20260915_102124.json` |
| 本地audit | 18字段双向EXCEPT ALL差异0，schema、空/重复键、文件分区对齐通过；函数17.54秒、CLI墙钟19.18秒；无prod业务重读 | `/private/tmp/daily_basic_p3_audit_20260915_102124.json` |
| 收口 | 实际范围2010-01-04至2026-09-14；正式目标文件仍0，提升/分区/event/prod业务写入均0 | `/private/tmp/daily_basic_p3_staging_final_audit_20260915_102124.json` |

plan fingerprint=`f9afae0f47fea8ac2bcfd7c675a215fdc00ba76547d79d58f0038b6309709c83`；export=`f56e76189ac0fc017800453f11cd3ec1bdd511c934c2f939096e5b137bbacf86`；build=`bb6982af188fd80c7dc34cf436680e4a0855a4605df131d3c59cba57ea896b17`；audit=`1df165b57aeaea998c565b73c2cf0956b0c58241929cc93caf841b54d7bb4dd7`。后续提升必须重核当前候选和目标，不以这些历史报告直接绕过锁与冲突检查。

实际体量：chunk446,804,795字节，最终按日候选761,591,306字节，整个staging含中间产物/checkpoint共1,678,610,886字节。2025年为最大年度，243日期、1,313,898行，低于先前1,470,000行容量样本。audit `/usr/bin/time -l`报告峰值RSS5,523,177,472字节（约5.14GiB），peak memory footprint6,949,181,056字节，未触发16GiB限制；构建spill残留0但未独立测峰值，不能宣称峰值为0。时间/RSS报告`/private/tmp/daily_basic_p3_audit_20260915_102124.time`，各阶段日志与报告同前缀。

本阶段完成的是staging数据，不是正式Lake发布。未运行promote、job/sensor、注册或runless event；P4也未进入。下一步单独推进正式文件提升及其物理审计，不重拉prod，不增加第二遍来源核验。本轮代码与文档未自动提交。

### 14.8 正式提升与物理验收（2026-09-15完成）

管理员在§14.7结果后批准继续。工作目录为`lake_console/orchestrator`，使用现有虚拟环境执行以下命令；本阶段不加载正式Dagster instance，不需要`DAGSTER_HOME`，不访问prod业务数据：

```bash
.venv/bin/python -B -u -m orchestrator.defs.bootstrap.daily_basic_history_cli promote \
  --apply \
  --plan /private/tmp/daily_basic_p3_execution_plan_20260915_102124.json \
  --fingerprint f9afae0f47fea8ac2bcfd7c675a215fdc00ba76547d79d58f0038b6309709c83 \
  --audit-report /private/tmp/daily_basic_p3_audit_20260915_102124.json \
  --report /private/tmp/daily_basic_p3_promote_20260915_102124.json
```

沿用已完成的隔离样本验证、全量staging构建与聚合审计，不修改plan范围或裁剪audit报告。执行前同卷与空间检查通过；工具持有history锁重新审核全部候选，再以日更同一日期锁逐文件提升，每个文件核hash并记录`promote.json`。任一异常停止，已完成文件由checkpoint与物理文件续跑核验；不承诺跨4,056文件整体原子。此次没有异常或目标冲突。

| 验收项 | 实际结果 |
|---|---|
| 正式文件 | `raw/tushare/daily_basic/trade_date=<ISO日期>/part-000.parquet`，4,056个文件，无额外文件 |
| 范围与行数 | 2010-01-04至2026-09-14，14,288,011行；正式Parquet页脚逐文件计数等于audit |
| 内容身份 | 所有正式文件SHA-256等于已审计候选；沿用候选18字段/schema/日期/key全量验收，未重复计算业务字段 |
| 正式体量 | 761,591,306字节，候选保留在原staging，不是原正式文件备份 |
| 性能 | CLI含全量提升前重审46.70秒，峰值RSS5,476,335,616字节；最终仅文件hash和页脚审计0.83秒 |
| 执行边界 | 本次prod业务读写0、DG事件写入0、动态分区写入0、job提交0、sensor状态变更0；不是宣称其它并行任务无状态变化 |

promote fingerprint=`d02a09e8ce5a0aee3c2f9ad2428e4c15b3fd35a076c293c112dada622060aef3`；报告`/private/tmp/daily_basic_p3_promote_20260915_102124.json`，日志与时间报告同前缀`.log/.time`。最终审计报告`/private/tmp/daily_basic_p3_publication_final_audit_20260915_102124.json`，脚本`/private/tmp/daily_basic_p3_publication_audit_20260915.py`，只读正式文件并输出临时报告。

本节记录P3发布时点：**当时P3正式物理发布完成、P4尚未进入**。随后P4开发结果见§15。不得仅凭本次文件发布生成绿色状态或自动启用sensor；P3本轮没有新增生产代码修改，原排序/门禁修正及两份文档当时尚未提交。

## 15. P4代码与只读plan验收

2026-09-15按管理员“继续推进P4”完成开发及只读plan，未申请/执行正式状态写入。CodeGraph `query/impact audit_daily_basic_coverage`及代码引用审计确认影响面为本族IO、check、readiness及其sensor消费者；新增离线events和instance适配器只由原CLI调用，active无反向导入。日更来源、最低覆盖、run key、job selection、分区定义、文件schema和路径不变。

| 约束 | 代码与测试证据 |
|---|---|
| 历史交付不依赖stock_daily | `daily_basic_raw_io.audit_daily_basic_coverage`新增prod_history身份校验；check/readiness按同一delivery_method决定是否读上游。测试禁止历史调用上游，缺失/错误身份与文件变化拒绝 |
| 状态范围与幂等 | `bootstrap/daily_basic_events.py`的plan/apply；21日fixture为21条materialization+40条check，sample后全量再跑为0新增。仅有materialization的首日仍不ready |
| 失败与恢复 | check-only、旧失败、不同交付、未注册、过期/变化plan、文件损坏、活动run拒绝；分别在materialization和check中途模拟API失败，新plan仅补剩余事件 |
| 绑定与并发 | 绑定storage id/run id/timestamp，批次前复核注册/check索引/materialization，check前核对当前文件与materialization；CLI写阶段使用`/private/tmp/daily_basic_event_publication.lock`非阻塞互斥，锁文件不删除 |
| 只读入口 | `daily_basic_event_instance.py`读取既有dagster.yaml，限制本机goldenshare_dagster，拒绝自定义storage；Postgres storage禁autocreate、plan默认READ ONLY/10秒timeout；不创建launcher/schedule，不执行DDL |
| 性能 | plan只hash全部文件，键/schema校验恰好20日；历史事件500日期分组、20,000返回上限。原日更10日fixture仍1次materialization查询、10次check批查询，实测约0.032秒 |

回归270项与166个subtests通过，`/private/tmp/daily_basic_p4_regression.log`；默认Ruff通过。catalog经既有`stock_suspend_confirmed_test_runner.py --scope regression --suite test_asset_governance_contracts.py`隔离启动器验证通过，`/private/tmp/daily_basic_p4_catalog_protected.log`。普通pytest运行该suite时缺少专用插件`stock_suspend_confirmed_test_support`，已改用规定启动器，未改测试预期或共享代码。历史事件夹具曾因同一runless check重复写入触发SQLite唯一约束，已改为先建立一次失败事实再验证拒绝；正常幂等路径从不重复追加已有check。

正式只读命令为原CLI `plan-events`，输入P3三份报告：`--plan /private/tmp/daily_basic_p3_execution_plan_20260915_102124.json --audit-report /private/tmp/daily_basic_p3_audit_20260915_102124.json --promote-report /private/tmp/daily_basic_p3_promote_20260915_102124.json`。输出`/private/tmp/daily_basic_p4_plan_events_20260915.json`，fingerprint=`b5d94c45208f33a9d0dea305b1163dbc1b0884188897b8f40ea2945196bf8181`。

| 正式只读结果 | 数量/状态 |
|---|---|
| 文件/历史行数基线 | 4,056文件，P3冻结14,288,011行，所有文件hash一致 |
| 待注册日期 | 4,056 |
| 待materialization | 4,056（现有0） |
| 待check | 40（现有0），2026-08-18至2026-09-14最近20个交易日 |
| 阻断与耗时 | should_stop=false，4.279秒；无本族活动run/冲突 |
| 正式写入 | 0；无Lake、prod、分区/event、job或sensor操作 |

**下一步是P4正式状态发布批准，不是继续重复开发历史工具。** 执行前重做一份1小时内plan；先注册，再重做plan并审批sample事件，sample通过再补余量，最后audit-events剩余清单为空并抽查readiness。最多4,096条事件，不补全历史check、不启用sensor。P5真实日更仍独立；当前代码与文档未自动提交。

## 16. P4正式日期注册完成

管理员继续推进授权后，本轮仅执行专属动态分区注册，事件写入仍独立。先重做只读plan，确认待注册4,056、待materialization4,056、待check40、无阻断，使用既有CLI `register --apply`及新鲜event plan fingerprint执行。

- 注册前：`/private/tmp/daily_basic_p4_before_register_20260915.json`，fingerprint=`172057dde6b666a78c49c69b42a172b4cc202acab523de44dfc6370dca5121d0`。
- 正式操作：仅经`DagsterInstance.add_dynamic_partitions`向`cn_a_daily_basic_trade_days`添加2010-01-04至2026-09-14的4,056个日期；报告`/private/tmp/daily_basic_p4_register_20260915.json`，registered_count=4056、event_count=0。
- 注册后：`/private/tmp/daily_basic_p4_after_register_20260915.json`，audit-events实测3.305秒，缺注册0、待materialization4,056、待check40、should_stop=false；文件hash全数一致。没有Lake/prod写入、事件写入、job或sensor操作，也没有改共享分区。

下一步是单独批准最近窗口样本事件补录，例如2026-09-14的一条materialization和两条check；新鲜plan后执行，样本ready且绑定正确才推进余量。注册本身不表示materialized或ready。本轮只同步原文档，不自动提交。

## 17. P4提交及样本事件验收

管理员要求“提交，然后继续推进”。已提交`9a8fdd7d`，仅包含本专项12个代码、测试与设计文件，包含此前P3排序/门禁修正；未推送，未混入其它工作区修改。

随后只执行2026-09-14样本，使用原CLI `report-events --apply --sample-date 2026-09-14`，输入同一P3三份报告和新鲜event plan：`/private/tmp/daily_basic_p4_before_sample_20260915.json`，fingerprint=`2eacfab06fb687d09e4ca29401cb217431edce6c0b228edd0f37834353e472d8`。执行报告`/private/tmp/daily_basic_p4_sample_20260915.json`确认恰好写入3条event，没有run、Lake或prod写入。

只读样本验收`/private/tmp/daily_basic_p4_sample_audit_20260915.json`：`batch_daily_basic_readiness`返回ready；materialization storage id=`7352719`；两条ERROR/blocking check均passed，partition均为2026-09-14，target storage id/run id/timestamp与本次materialization一致。注册无缺口，正式文件hash仍全部一致。

剩余plan为`/private/tmp/daily_basic_p4_after_sample_plan_20260915.json`：4,055条materialization、38条check，共4,093条。余量需单独批准并刷新1小时内plan，再执行不带sample-date的report-events，最终全量剩余清单为0并抽查最近窗口readiness。未启用sensor或进入P5。本节样本执行记录为提交后的文档更新，尚未提交。

## 18. P4余量补录与最终验收

管理员批准继续后，刷新`/private/tmp/daily_basic_p4_before_remaining_20260915.json`，fingerprint=`51b8d64d378f2a0261d1f02185223cb816ccd3762e01c0c4263cf9f00f1622c3`。原CLI以`report-events --apply`绑定此plan，跳过已完成样本，写入4,055条materialization和38条check。执行报告`/private/tmp/daily_basic_p4_remaining_20260915.json`记录event_count=4,093，fingerprint=`d067b5d564b474b6dbf4bf4176a85df78090d727061ed01da965ac3804a8e013`。

最终只读报告`/private/tmp/daily_basic_p4_final_audit_20260915.json`及冻结plan`/private/tmp/daily_basic_p4_final_plan_20260915.json`确认：

- 4,056个候选日期全部注册、全部有materialization；缺注册、待materialization、待check均为0。
- 累计事件4,096条：4,056条materialization、40条check；样本3条、余量4,093条。
- check仅覆盖2026-08-18至2026-09-14最近20个交易日，窗口外为0；check身份和target materialization一致，按10日批次复核20日readiness全部ready。
- 全部4,056个正式文件hash与P3已审计发布结果一致；最终plan耗时2.914秒。更早日期只发布materialized，不声称具备blocking-check readiness。
- 本轮Lake/prod写入、job启动、sensor改动均为0，未进入P5。

§16、§17保留注册和样本时点的历史记录，当前P4状态以本节为准。执行结果已回写原两份文档，本次记录尚未提交。
