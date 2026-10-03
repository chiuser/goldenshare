# DG 股票周线：Prod 存量保留与备用源 Raw 补齐方案 v1

日期：2026-10-03，Asia/Shanghai。状态：M0 开发前核验已收口，M1 纯合同与规划器已完成并验证；[代码级 LLD](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)已对账。M2捕获器、M3年度候选与单文件提升恢复、M4定义集成与受限单周手动交付已实现并完成隔离验收；尚未执行正式 bootstrap、写入正式 Lake 或提交 Dagster 任务。账户配额由管理员确认足够，不再作为待核实门禁。

LLD 已细化主源两张资产的逐字段类型／精度及列白名单、局部配置审计、模块接口与消费者影响面、manifest/checkpoint、错误／续跑与测试。2026-10-03 Prod 只读系统目录核验表明仅有代码前缀主键索引，所以历史导出进一步明确为代码批次×年窗口；三张主源技术采集列不进入行情 Parquet，详见 LLD §4。真实分页和代表样本 Decimal/耗时/压缩大小已于 M0 核验；全体退市可用性和身份分支在后续有界调查中逐批准入。M1 详情见 [开发验收记录](../../../reports/stock_week_m1_assessment_20261003.md)。

## 1. 决策与完成边界

按管理员最新决定，停止在 Prod 回补剩余历史股票周线。DG 先完整接收 Prod 已有周线，再从 Tushare `weekly` 获取主源缺失的历史行情。两类源事实在 Raw 分开存储，覆盖审计按等价自然周取并集。

第一阶段交付是 **未复权、复权两套周线的 bootstrap 和更新机制开发**，包括主源新增数据下载、周期日期规划、有界分页、候选校验、幂等写入、失败续跑和定向任务集成；不能仅交付存量复制。备用 `weekly` 是独立未复权历史补齐来源，不能填进 qfq/hfq 列。两套周线完成并验收后，第二阶段完成未复权、复权两套月线的 bootstrap 和更新机制开发。复权历史缺口与更新能力分别验收，不能因源不可用而取消复权数据集开发；自行重建复权不属于已批准范围。

Raw 对齐 Tushare 源字段，不包含 Prod 的 `api_name/fetched_at/raw_payload` 等采集信息；执行审计证据放在 staging receipts 和运行 metadata，不混入行情字段。

管理员补充口径：退市股票通过 `weekly` 补齐未复权历史，以及后续复权历史补齐，均按“能补尽量补，确实无法补齐不强求，但必须记录”验收。已核实无可用来源的历史缺口不阻塞两套数据集 bootstrap／更新机制的交付，不要求为了清零缺口而自行计算或伪造行情；可取得且通过契约校验的数据仍须完成写入和对账。请求失败、超时、权限不足、身份未决或尚未核验不能当作“确实无数据”，须如实记为未解决事项，按既有预算处理，不无限重试。

执行时在 `reports/` 留存逐代码、逐周期、逐复权类型的 CSV 缺口台账及汇总，至少记录原始代码／核实后的身份、频度、周期、未复权/qfq/hfq、尝试接口、查询区间、核验时间、响应行数、结果分类、原因、证据引用和后续建议。连续缺口可另外汇总区间，不能丢失精确周期。台账同时区分已补齐、已查无源、请求失败和待核验；本次只定义台账契约，不将旧调查直接改判为已完成。该原则随第二阶段月线 LLD 继承。

历史起点按当前 Prod 对应频度的最早行情日期确定，不再固定为 2010 年。冻结计划前只读核验未复权／复权两表的 week、month 四组最早日期；同一频度的审计下界取两组最早日期中的较早者，各主源 bootstrap 均保留自身全部历史记录。备用周线补齐对齐该周线下界，并按首周边界展开请求。源没有数据的更早周期独立列明，不凭日历制造缺口。旧审计只覆盖 2010-01-01 至 2026-09-25，不能替代新范围完整性验收；日线依据、请求／文件预算须重算。2026-10-02 所在周仍按管理员指示暂不补；该排除不永久禁止后续新增同步。月线 2020 年 2 月只使用 28 日的既定决定不变，需在月线专项 LLD 区分 Raw 源保留与正式周期选择。

## 2. 已有证据与尚待验证项

2026-10-03 已执行 M0，只读 [核验报告](../../../reports/stock_week_m0_assessment_20261003.md)。当前周线最早均2010-01-01、月线均2010-01-31；周线两主源总5,787,046行，三接口完整分页各52键闭合；代表样本各15,346行Decimal写出/读回差异为零。原2010起点与管理员批准Prod起点一致；年份应为17年。管理员已确认账户配额充足；M0 开发前核验收口，M1 已通过。更新编排集成与正式运行验收属于后续切片。

Prod 数据快照截至 2026-10-02 22:40；不是 10 月 3 日重新全库统计。依据见 [完整周线复核](../../../reports/stock_week_completed_full_reaudit_20261002.md)、[缺口对象与区间](../../../reports/stock_week_historical_remaining_code_ranges_20261002.csv)、[退市源验证](../../../reports/stock_week_delisted_source_assessment_20261002.md)。

| 已完成周候选类别 | Raw 未复权缺失键 | Raw 复权缺失键 | 本方案处理 |
|---|---:|---:|---|
| 退市股票 | 103,637 | 108,156 | 未复权逐对象查备用源，先做 5 只试点 |
| 北交所／身份候选 | 62,563 | 62,563 | 先核验历史代码映射及源支持，不能直接视为缺行情 |
| 身份未确认 | 897 | 897 | 核验 000022.SZ、000043.SZ 的历史身份后处理 |
| 合计 | 167,097 | 171,616 | 是日线推导的候选，不能直接当可补行数 |

未复权候选涉及 462 个代码：退市 211 个、北交所／身份候选 249 个、身份未确认 2 个。2026 年截至 9 月 25 日，已审计的现存上市沪深股票历史候选缺口为零。不得把“退市”一律当缺口或一律排除。

备用源已有 5 只退市股票真实请求；当前主源 `stk_weekly_monthly` / `stk_week_month_adj` 对这些样本为空，`weekly` 有历史数据。将备用源日期映射至同一自然周后，覆盖下列 3,132 个未复权候选键：

| 代码 | `weekly` 对象全历史返回行数 | 已覆盖候选周数 |
|---|---:|---:|
| 000005.SZ | 1,488 | 656 |
| 000961.SZ | 1,179 | 732 |
| 002089.SZ | 831 | 674 |
| 300090.SZ | 473 | 473 |
| 600090.SH | 1,193 | 597 |

5,164 是源响应总行数，含审计起点以前及非缺口记录；不能作为本轮新增写入行数。该证据证明样本周期覆盖，不等于全部字段、复权或全体退市股票已验收。

10 月 3 日补充 [字段与区间实测](../../../reports/stock_week_alternate_contract_probe_20261003.json)：000005.SZ 的 2020 年区间返回 52 行、显式 11 列；2024-03-08 默认返回 1 行、同样 11 列。此前对象历史请求显式带了身份／时间关键列 `ts_code,trade_date,close`。MCP 不暴露 limit/offset；后续 M0 已用既有 SDK 完成真实分页验收，见 M0 报告。

10 月 3 日 [重叠样本实测](../../../reports/stock_week_alternate_overlap_probe_20261003.json) 表明不能直接拼接两源：

| 000001.SZ，同一自然周 | 主源 | `weekly` |
|---|---|---|
| 日期 | 2026-09-25 | 2026-09-24 |
| close / open / high / low | 11.30 / 11.70 / 11.75 / 11.29 | 相同 |
| vol | 3,527,557 | 352,755,700 |
| amount | 4,080,639.78 | 4,080,639,783.47 |
| pct_chg | -3.42 | -0.0342 |

9 月其余三个已完成周样本也呈现 vol 100 倍、amount 约 1,000 倍及 pct_chg 百分比／比例差异。成交额存在舍入误差，不能要求浮点完全相等。`weekly(trade_date=20260925)` 为空，区间请求能返回 20260924，所以补齐采用对象＋区间，不按主源星期五日期机械点查。

本地源文档：[weekly](../../../docs/sources/tushare/股票数据/行情数据/0144_周线行情.md)、[主源未复权](../../../docs/sources/tushare/股票数据/行情数据/0336_股票周_月线行情(每日更新).md)、[主源复权](../../../docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md)。`weekly.pct_chg` 文档明确为未乘 100 的比例；成交量／成交额跨市场与历史区间的单位仍须扩大样本核验，不能只凭上述比例推广全部记录。

## 3. Raw 存储与资产事实卡

以下名称、路径及分区模型均为拟新增，不是当前正式资产。M1 已新增三源路径和纯合同；当前 `LAKE_ASSET_CATALOG` 尚未登记股票周线，活跃资产将在 M4 同步接入。资产长期按来源命名，不使用 temporary/history/bootstrap 作为资产职责。

| 项目 | 主源未复权 | 主源复权 | 备用源 |
|---|---|---|---|
| 拟定 asset key | `raw_tushare_stk_period_bar_week` | `raw_tushare_stk_period_bar_adj_week` | `raw_tushare_weekly` |
| 中文名 | 股票周线原始行情 | 股票周线原始复权行情 | 股票周线备用源原始行情 |
| 来源 | Prod `raw_tushare.stk_period_bar`，`freq='week'`；新增用 `stk_weekly_monthly` | Prod `raw_tushare.stk_period_bar_adj`，`freq='week'`；新增用 `stk_week_month_adj` | Tushare `weekly` |
| 数据角色 | 主源镜像 | 主源镜像 | 独立备用源镜像 |
| 源业务 key | `ts_code,trade_date,freq` | `ts_code,trade_date,freq` | `ts_code,trade_date` |
| 拟定正式相对路径 | `raw/tushare/stk_period_bar_week/week_end={key}/part-000.parquet` | `raw/tushare/stk_period_bar_adj_week/week_end={key}/part-000.parquet` | `raw/tushare/weekly/week_end={key}/part-000.parquet` |
| 分区坐标 | 源日期所属 ISO 自然周的星期五，`YYYY-MM-DD` | 同左 | 同左 |
| 文件内部日期 | 保留源字符串，不改写异常历史日期 | 同左 | 保留源实际交易日期，不改为星期五 |
| 依赖 | Prod 只读资源／Tushare 资源、Lake 路径资源 | 同左 | Tushare 资源、Lake 路径资源 |

正式根唯一为 `/Volumes/datasource/data_lake`；候选、审计与 checkpoint 唯一放在 `/Volumes/datasource/data_lake_staging/stock_weekly_raw/plan_hash={hash}/`。不得读取旧 Lake，不运行 Kopia，不把 staging 当正式覆盖事实。

Raw 保留源代码、源日期、源价格和源单位；不按 current-listed 删除退市历史，不伪造备用源不存在的 `freq/end_date/qfq/hfq`。来源由资产身份和 run metadata 表达，不额外注入 Raw 业务列。主源 Raw 全量保留 Prod 历史源业务字段；技术自增 ID／写入时间是否进入业务 Parquet须在 bootstrap 列白名单逐列确认，不能静默丢失。

备用源在冻结对象／区间内的所有返回记录都落 Raw，包括与主源重叠的记录；不只保留缺口行。重叠是独立源事实，用于对账及以后重算。增量补齐按同源 key 合并已有备用 Raw；同 key 同值幂等，异值记录修订证据并阻止无审批覆盖。禁止用新批次少量代码覆盖一整周文件中的其他代码。

### 字段契约草案

备用 Raw 明确字段顺序为源默认顺序。以下类型是拟定显式 Parquet schema；上线前必须用返回样本与实际写入读回验证，不依赖 DataFrame 推断。

| 源／Raw 字段 | 源返回类型 | 拟定 Raw 类型 | 可空策略及说明 | 后续 Silver 映射 |
|---|---|---|---|---|
| ts_code | 字符串 | VARCHAR | 必填；保留源代码 | 通过历史 identity map，保留 source_ts_code |
| trade_date | YYYYMMDD 字符串 | VARCHAR | 必填；合法日期、所属分区周匹配 | source_trade_date: DATE；另生成 week_end: DATE |
| close | 数值 | DOUBLE | 必填；空值阻止候选提升 | 原价格 |
| open | 数值 | DOUBLE | 必填；空值阻止候选提升 | 原价格 |
| high | 数值 | DOUBLE | 必填；空值阻止候选提升 | 原价格 |
| low | 数值 | DOUBLE | 必填；空值阻止候选提升 | 原价格 |
| pre_close | 数值 | DOUBLE | 暂允许 NULL，须报告数量与样本 | 原值；不自行补上一周 |
| change | 数值 | DOUBLE | 暂允许 NULL，须报告 | change_amount |
| pct_chg | 数值 | DOUBLE | 暂允许 NULL；保留比例 | 如统一为百分数则乘 100 |
| vol | 数值 | DOUBLE | 必填；零值保留、负值阻止提升 | 单位核验后转为共同单位 |
| amount | 数值 | DOUBLE | 必填；零值保留、负值阻止提升 | 单位核验后转为共同单位 |

字段契约及列类型集中在现行 `ColumnContract` / `asset_column_schemas.py`，由其派生请求列、写入列和 checks；definition metadata 注册 `dagster/column_schema`，运行时只记录 observed columns、源参数、行数、URI、耗时等事实。物理字段检查用 `hive_partitioning=false`，目录虚拟列 `week_end` 不算 Raw 文件字段。

主源 13 列、复权源 21 列沿用原评估的源字段集。LLD §4 已按真实 Prod catalog 将价格定义为 DECIMAL(18,4)、成交量／额为 DECIMAL(20,4)、涨跌幅为 DECIMAL(10,4)，保持 NULL，日期转为源格式字符串；具体投影、技术采集列排除及精度损失拒绝策略以 LLD 为准。实际 Parquet 无损读回和新 Tushare 响应精度仍须验收。最终“Raw 已补齐”要求主源 bootstrap 和获准备用补齐分别完成。

## 4. 时间、请求与覆盖三层语义

1. **运营输入**：获准历史对象名单和周期范围；代码显式列表按对象 fan-out，不逗号拼接给 API。Raw 的周期分区坐标不等于源端请求日期。`limit/offset/fields` 不自动作为运营输入。
2. **执行 unit**：备用源采用一只股票＋一年日期窗口。自然周期首尾可能跨年，因此 planner 从自然周边界展开源请求区间，再按源日期归属的周分区路由；例如锚点 2010-01-01 的周从 2009-12-28 开始，不可只查 20100101 而漏掉更早交易日。允许窗口边界重叠，按源 key 幂等去重并报告数量。
3. **覆盖审计**：基于同一身份在某周有实际日线记录形成期望键；对 primary Raw 与备用 Raw 分别归一成 `(canonical_code, ISO_week)` 后取并集。日线只用于候选覆盖，不能据日线自行构造周 OHLC。

拟新增独立自然周分区模型，不能套用现有 `stock_trade_days` 日线分区。无交易的整周不要求非空文件；空周跳过、源空响应与源请求失败必须区分。对有日线的周仍缺失时逐键归类：源可补、已核实源无数据、身份待确认、字段／单位未验收、尚未查源。只有明确查询成功、字段正常的源空结果才可记“该接口该范围暂无可用数据”，不能推断所有备用源永久不可补。

备用源是历史补齐资产，不接日常更新 sensor，不要求每天新鲜。两套主源的更新机制属于第一阶段，使用 Prod 的自然周五业务日期策略并显式传入已完成锚点，避免把节假日的最近开市日误作自然周锚点。主源任务触发、源可用性、周期完成门禁、分页预算与历史修订处理须在编码前补齐 LLD；正式调度启用另按执行阶段授权。备用自动修复不附带开发。

## 5. Silver 建议与复权边界

2026-10-03 [字段实测](../../../reports/stock_week_adjustment_field_probe_20261003.json)：000001.SZ、20260918，weekly 默认与显式 11 列一致；显式请求 qfq/hfq/adj_factor 后只返回 ts_code/trade_date/close；复权主接口返回 close=11.70、close_qfq=11.45、close_hfq=1626.39。结论限于接口合同及样本：weekly 不提供复权字段，Tushare 另有复权主接口。退市复权样本为空不能推广成所有股票无复权来源。

Raw 补齐本身不要求发布 Silver；但以后要提供一份可消费周线，建议新增轻量 Silver 合并，而不是将两套 Raw 原值直接 UNION。这里对原先“Silver 可能不用清洗”的判断作最小修正：**需要统一周期与单位，不从日线重算行情**。

拟定粒度 `(canonical_code, week_end)`，保留 `source_api/source_ts_code/source_trade_date`。同周主源存在则优先主源；备用只填主源缺失。若重叠值不一致则报告差异，禁止自动覆盖主源或平均价格。代码映射复用历史身份事实，不用现存上市清单替代生命周期。

建议统一成交量为股、成交额为元、涨跌幅为百分数；在上述已实测样本中，主源分别乘 100、1,000，备用源保持成交量／成交额原值且涨跌幅乘 100。最终转换以跨历史区间、跨市场源核验为门禁；Gold/Serving 的单位及现行日线消费者需单独审计，本文不批准改变其契约。数值对账采用源精度对应的舍入容差，不随意设置宽松阈值。

复权主源继续独立保留、单独统计缺口。不能拿未复权 `weekly` 填 qfq/hfq，不能简单套周末单一 adj_factor 推出整周四价，也不能承诺沿用 Prod 的复权基准而不验证。当前复权历史缺口作为独立已知限制，不影响未复权补齐的完成定义。

## 6. 请求、内存、文件与恢复预算

以下历史规模数字基于旧 2010 年起点，仅作已有证据参考。当前批准起点改为 Prod 对应频度最早日期后，M0 必须重算年份、请求、分区、事件、耗时与空间；旧数字不能作为新范围完整预算；M0已给出当前行数、212个unit/source的年库存算法及2363个退市code/year候选，具体以LLD §18和预算JSON为准。

以下为待实测收敛的离线执行计划预算，不是已存在的配置。预算随冻结 manifest 持久化，禁止散落在页面、代码和文档形成不同默认值。正式运行前必须记录批准值、计划 hash 及实测耗时。

| 项目 | 方案预算／策略 |
|---|---|
| 试点 | 上述 5 只；2010–2025 各有候选的年窗口；最多 80 次年度请求，边界复核另列 |
| 退市推广 | 211 对象 × 最多 16 年 = 3,376 次请求上界；只查存在候选的窗口可下降；并非全市场对象×全部周 |
| 身份分支 | 251 对象先做身份及源支持调查；不得直接加入 3,376 次预算 |
| 单源请求 | 单代码年度窗口，正常最多约 53 周，按不超过 54 行的有界期望校验；遇超过预期、重复周或返回 6,000 行立即停止核验，不能认作全集 |
| 分页 | 当前 MCP 无 limit/offset；年度有界请求避免依赖无界全集分页。正式资源仍须验证 limit/offset 与满页反例后才能宣称通用分页已验收；不自动使用未验证的参数 |
| 配额与耗时 | 初始建议单并发、最多每秒 1 次且不超过账户实际额度；3,376 次仅请求间隔约 56 分钟，真实耗时另加源延迟、限流、候选写入和审计。不能把该下限当 ETA |
| 请求及重试上限 | manifest 记录计划调用数；建议至多 2 次有界重试，实际配额成本可达基础请求量的 3 倍；超限暂停，禁止无限重试 |
| 工作批次 | 源捕获工作批次最多20对象、一年窗口，每unit立即持久化；同来源同年度的批准对象捕获齐后只构建／提升一遍该年度周分区，不随每个对象批次反复重写 |
| DuckDB | 复用 configured DuckDB 资源；建议进程内存预算 512 MiB，spill 只能在获准 staging；正式值经现有配置审计后冻结，不覆盖全局配置 |
| 主源导出 | 表／列／freq 白名单；ProdPostgresResource rollback-only 只读事务及服务端游标，fetchmany 10,000 行；按代码批次（最多300）×年窗口利用现有主键索引，一unit一连接，控制聚合／stream SQL均计预算；不按无代码约束的年份反复扫全表 |
| 输出粒度 | 一来源一自然周一个正式 Parquet；源读取按对象年，写入按周，按源 key 合并全文件。冻结计划须先测实有周数、行数及压缩字节，不能以覆盖候选数代替导出行数 |
| 文件上界 | 2010-01-01 至 2026-09-25 最多 874 个自然周坐标／来源，实际无交易周可更少；Prod 更早存量额外单列。不得按代码生成几千份小文件／周 |
| 取消与进度 | 每源调用前后、每 fetch batch、每文件提升前检查取消；显示阶段、当前代码／窗口、完成 unit 数、总量、最近更新时间。进度随每 unit checkpoint 更新，超时调用不得领取新 unit |

正式请求超时、statement timeout、连接上限、内存/spill 与批次值必须在开发前配置审计卡登记：名称、来源、默认值、持久化位置、消费者、依赖、生效方式、运维展示和测试。优先复用现有资源设置；新预算放版本化运行 manifest，不新增散落的环境变量。

安全写入顺序：冻结范围与目标指纹 → 构建 run-scoped 候选 → 全部候选校验 → 明确批准的 promote → 同文件系统逐文件 `os.replace()` → 读回与 checkpoint。提升前确认 staging 与正式目标同文件系统；不同则阻止。逐文件原子不等于整批原子，取消／退出后按 checkpoint 加正式文件指纹续跑，不删除异常现场，不做文件备份或快照。

同一正式周文件只允许一个写入者；不同对象批次不能并发改同一文件。candidate_manifest 必须冻结各源 unit、schema、文件 hash、源计数、重复计数及目标基线，target fingerprint 变化则重新审计，禁止覆盖他人更新。

## 7. Checks、测试与验收

生产检查以物理事实为依据：源字段／类型、源 key 唯一且非空、源日期可解析并属于目标周、文件完整可读、源范围符合冻结清单、源端→候选→目标行数可解释。Raw 不因退市、停牌、零成交量或异常历史日期擅自过滤记录；异常标记进审计报告。

覆盖审计作为显式离线批次运行，按文件列表／年份向量化读取；日常生产 check 不扫描全历史、不重复转换、不从输出倒推“源完整”。checks 不写 Raw，不为历史全绿伪造事件。bootstrap/runless materialization 及 check event 另列精确数量预算与独立批准范围；文件存在不自动等于事件已登记。

最低测试覆盖：节假日非星期五源日期、跨年周、整周无交易、代码变更／退市历史、未查源与空源区分、源列缺失、零列响应、重复源 key、单位换算及舍入、同周主源优先、备用不得填复权、子集更新保留其他代码、候选破损、指纹变化、中途取消／退出／续跑／幂等。Gold 业务公式无需在此新增。

真实验收分开报告以下事实，不以 run success 代替物理完整：

1. Prod bootstrap：源表精确范围／字段、读取行数、写入行数、目标读回行数、每类排除／拒绝及样本；正式主源与获准 Prod 投影一致。
2. 备用试点：源响应行数、Raw 源 key 数、重叠／重复计数、写入／读回计数、候选 3,132 键闭合情况。正式调用时刷新源快照，旧样本数量只用于比较，差异逐项解释。
3. 推广：逐对象逐周分类；源不可用和身份未决单列，禁止声称所有 167,097 键均可补。复权缺口仍独立报告。
4. 性能：实际请求／重试／SQL／连接次数、峰值内存、最慢 unit、文件数及大小、中断恢复证据；不以设计预算冒充实测。

## 8. 实施切片与影响面

| 阶段 | 交付 | 执行边界 |
|---|---|---|
| A：只读来源及计划冻结 | 扩大单位与字段样本；211 退市代码可用性清单；身份分支；主源列白名单；配置审计；填接入模板 §3、§7/7A、§8、§18 | 不写正式 Lake／instance |
| B：代码与候选能力 | 注册三张 Raw 的 schema/path/catalog/自然周模型；独立有界历史工具；定向测试及无副作用 definitions 验证 | 开发范围已明确；不自动运行任务 |
| C：主源 bootstrap | Prod 全量周线只读导出、候选对账、获批后提升 | 先样本后年度批次；两源存量分别验收 |
| D：备用 5 只试点 | 固定窗口源下载、候选校验、获批后提升、物理覆盖对账 | 源字段合格才进入 promote；先证明未复权 |
| E：其余可补对象 | 先退市，再已核实身份分支；有界批次与最终审计 | 每批遵守冻结范围；不可补另报 |
| F：两套周线更新机制 | 两主源新增下载、周期规划、任务触发设计、幂等／修订处理、分页和失败续跑 | 第一阶段必交付；正式启用按阶段授权 |
| G：两套月线 | 周线验收后，形成月线专项 LLD，完成两套 bootstrap 和更新机制 | 第二阶段；先审计月线源与日期语义 |
| 后续消费层 | Silver 日期／单位合并及自行复权重建 | 单独设计，不附带实施 |

已使用 CodeGraph `codegraph_explore` 核验 DG catalog、paths、资源与分页链路；当前 `TushareResource.call` 要求显式 fields，`ProdPostgresResource.connect_readonly_transaction` rollback-only，`_fetch_all_pages` 在内存累积全部页。其既有通用写入 helper 不具备完整独立 staging/checkpoint 保证，所以不能只复用名称便称满足本方案，也不在此修改所有现行消费者。

拟影响文件域：`defs/catalog/lake_assets.py`、分区模型注册、`defs/paths.py`、`defs/run_contracts/asset_column_schemas.py`、新增 weekly assets/checks、有界 bootstrap 工具及定向测试。开发前须进一步核验 exact symbols、definitions discovery、catalog static gates、run metadata、资源配置、历史身份消费、partition mapping、asset job selection、readiness 与自动调度消费者；主源新增维护属于第一阶段明确切片，Silver 另行设计；不能因代码注册而隐式激活正式任务。M1 只定义 schema/path/动态周分区和纯 planner，active catalog entries/partition models、typed Dagster config 和执行 definitions 在 M4 一次对齐，避免 registry 宣称资产存在而实现尚缺。

不改变 `src.foundation` / `src.ops` / `src.biz` 的数据集契约、Prod request builder、TaskRun 手动入口、现行 Quote API 或前端。无新增反向依赖；Dagster metadata/event 失败不能回滚已提升业务文件，须留下可恢复观测记录。

依据：[新增数据集模板](../templates/dagster-dataset-onboarding-template.html)、[性能治理](dagster-data-pipeline-performance-governance.md)、[Schema Contract](dagster-asset-schema-contract-design.md)及根／lake_console／orchestrator AGENTS。Dagster 资产、分区与资源使用现行架构；官方参考：[资产定义](https://docs.dagster.io/guides/build/assets/defining-assets)、[分区示例](https://docs.dagster.io/examples/full-pipelines/etl-pipeline/partition-asset)、[外部资源](https://docs.dagster.io/guides/build/external-resources)。资产页面已通过官方搜索摘要核验，页面直读因工具重定向不可用；本轮未加载正式 definitions、运行 dg job 或访问正式 instance。


### M3开发进展（2026-10-03）

M2已提交30b118ff，未推送。M3按照LLD年度合并/完整校验/单文件原子提升与恢复实现，详见[M3验收](../../../reports/stock_week_m3_assessment_20261003.md)。两主源各15346行及备用51行仅在私有临时目录构建和读回；NULL、非周五及existing-only保留，冲突/证据变化阻断，真实进程退出可续跑。M3已提交1638d42b，未推送；正式Lake/instance、bootstrap及更新启用均未执行。下一阶段M4接入definitions，历史完整性与源不可补台账仍按后续阶段验收。

### M4开发进展（2026-10-03）

三份Raw asset、九个blocking checks、三个精确selection手动jobs，以及catalog/名称/自然周partition model和受限typed config已接入。单周交付复用M2捕获和M3候选/原子提升；全量definitions加载和分区事件隔离验证通过，218项回归及治理门禁通过，详见[M4验收](../../../reports/stock_week_m4_assessment_20261003.md)。本轮修改尚未提交；正式bootstrap/事件/分区注册/调度均未执行。下一阶段M5须冻结真实库存和执行范围，M9自动更新仍待完成。
