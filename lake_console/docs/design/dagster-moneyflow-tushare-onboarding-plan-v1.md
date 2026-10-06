# Dagster 七个 Tushare 资金流向数据集接入技术方案 v1

> 状态：数据集与来源范围已由管理员确认；本技术设计待评审，尚未开发、bootstrap 或启用自动化。
>
> 日期：2026-10-06。目标：将 Prod 已有七个 Tushare 资金流向数据集接入正式 DG；历史从 Prod Raw 初始化，新增由 DG 直接请求 Tushare。
>
> 本文是实施方案，不是生产执行授权。后续 LLD、代码与执行结果必须回填本文；未完成的来源验证和验收不能预填通过。

## 1. 已确认范围

历史来源固定为 Prod PostgreSQL 的 **`goldenshare` 数据库、`raw_tushare` schema**。七个对象经目录核验均为物理表；管理员所说的“Prod Raw”指这一层，不是融合后的 serving 视图或表。

| 数据集 / 日更接口 | 内容 | 历史来源表 |
| --- | --- | --- |
| `moneyflow` | 个股大小单买卖量、金额和净流入 | `raw_tushare.moneyflow` |
| `moneyflow_dc` | 东财个股资金流向 | `raw_tushare.moneyflow_dc` |
| `moneyflow_ths` | 同花顺个股资金流向 | `raw_tushare.moneyflow_ths` |
| `moneyflow_ind_dc` | 东财行业、概念、地域板块资金流向 | `raw_tushare.moneyflow_ind_dc` |
| `moneyflow_ind_ths` | 同花顺行业资金流向 | `raw_tushare.moneyflow_ind_ths` |
| `moneyflow_cnt_ths` | 同花顺概念资金流向 | `raw_tushare.moneyflow_cnt_ths` |
| `moneyflow_mkt_dc` | 东财大盘资金流向 | `raw_tushare.moneyflow_mkt_dc` |

东财板块三类属于一个数据集，不拆成三个业务数据集。本次不读取 BIYING、`stockdb.public`、`core_multi.moneyflow_std` 或融合后的 `core_serving.equity_moneyflow`；不新增 `moneyflow_hsgt`。

本次建设 Raw、Silver 和必要的 DG 编排、检查及历史初始化工具。不建设 Gold 指标、跨来源融合、ClickHouse/Prod 发布、页面或新 API，不切换现有 Prod 采集与消费者。DG 的日更不以 Prod TaskRun、Prod 完成快照或生产对象池为前提。

## 2. 依据与当前事实

规则依据：

- [子系统边界基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)。
- [Orchestrator 规则](/Users/congming/github/goldenshare/lake_console/orchestrator/AGENTS.md)、[编码规范](/Users/congming/github/goldenshare/lake_console/orchestrator/CODING_STANDARDS.md)。
- [接入模板及来源预算 7A](/Users/congming/github/goldenshare/lake_console/docs/templates/dagster-dataset-onboarding-template.html#source-contract-budget)、[性能治理规范](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md)、[字段 schema 规范](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-asset-schema-contract-design.md)。
- Dagster 官方 [assets](https://docs.dagster.io/guides/build/assets)、[resources](https://docs.dagster.io/guides/build/external-resources)、[partitions](https://docs.dagster.io/guides/build/partitions-and-backfills)、[asset checks](https://docs.dagster.io/guides/test/asset-checks) 文档。

代码依据：

- [Prod DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/moneyflow.py)、[请求生成](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)、[普通资金流发布链](/Users/congming/github/goldenshare/src/foundation/ingestion/moneyflow_publish.py)。
- [DG 资源](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/resources.py)、[有界分页策略](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/tushare_request_policy.py)、[路径](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/paths.py)、[资产 catalog](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py)。
- [东财板块初始化实现](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/bootstrap/dc_board_bootstrap.py)仅用于理解已有分批导出能力，不能继承其数据范围、Prod 完成门禁或板块关系。

2026-10-06 审计发现当前 DG catalog、资金流相关 definition/schema/job/sensor 搜索均未发现本次七数据集接入。正式 Lake 已读取的 Raw/Silver 目录层级也未发现对应资金流目录；这不是全盘递归物理审计。

### 2.1 Prod 与源端样本

| 数据集 | Prod 日期边界 | 目录估算行数 | 2026-09-30 Prod / Tushare 行数 |
| --- | --- | ---: | ---: |
| `moneyflow` | `600000.SH` 样本为 2010-01-04～2026-09-30 | 13,817,325 | 未做整日计数 / 5,572 |
| `moneyflow_dc` | 2023-09-11～2026-09-30 | 4,194,716 | 6,024 / 6,024 |
| `moneyflow_ths` | 2024-12-19～2026-09-30 | 2,098,789 | 5,215 / 5,215 |
| `moneyflow_ind_dc` | 2023-09-12～2026-09-30 | 341,330 | 1,031 / 1,031 |
| `moneyflow_ind_ths` | 2024-09-10～2026-09-30 | 44,460 | 90 / 90 |
| `moneyflow_cnt_ths` | 2024-09-10～2026-09-30 | 181,947 | 387 / 387 |
| `moneyflow_mkt_dc` | 2023-04-17～2026-09-30 | 834 | 1 / 1 |

七表目录估算合计 20,679,401 行；表和索引合计 5,684,764,672 字节，含内部 payload 和索引，不能当作投影后的网络流量或 Parquet 大小。源端当日合计 18,320 行。东财板块 Prod 当日分别为行业 496、概念 504、地域 31，代码非空且各类代码数与行数一致；这不能外推为全历史代码完整。

上述是有界只读样本：估算行数不是精确总数，日期首尾不是连续性证明，六个接口当日行数一致不是逐字段一致或全历史完整证明。初次审计报告位于 `/private/tmp/moneyflow_prod_audit_20261006.json`、`/private/tmp/moneyflow_tushare_probe_20261006.json`；临时文件可能清理，本文保留了本轮关键事实，执行前重新形成冻结报告。

### 2.2 源文档与尚缺的证据

| 接口 | doc_id / 本地源文档 | 本地文档单次上限 |
| --- | --- | ---: |
| `moneyflow` | 170：[个股资金流向](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/资金流向数据/0170_个股资金流向.md) | 6,000 |
| `moneyflow_dc` | 349：[东财个股](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/资金流向数据/0349_个股资金流向（DC）.md) | 6,000 |
| `moneyflow_ths` | 348：[同花顺个股](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/资金流向数据/0348_个股资金流向（THS）.md) | 6,000 |
| `moneyflow_ind_dc` | 344：[东财板块](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/资金流向数据/0344_东财概念及行业板块资金流向（DC）.md) | 5,000 |
| `moneyflow_ind_ths` | 343：[同花顺行业](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/资金流向数据/0343_同花顺行业资金流向（THS）.md) | 5,000 |
| `moneyflow_cnt_ths` | 371：[同花顺概念](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/资金流向数据/0371_同花顺概念板块资金流向（THS）.md) | 5,000 |
| `moneyflow_mkt_dc` | 345：[东财大盘](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/资金流向数据/0345_大盘资金流向（DC）.md) | 3,000 |

已完成七接口按日期的默认字段请求、显式完整字段样本和关键身份字段样本。另实测 `moneyflow.trade_count` 存在，但当前 Prod Raw 与选定业务字段没有该列，本方案不新增它，也不声称源接口没有该字段。

`moneyflow_dc` 实测可返回 6,024 行，MCP 描述为 8,000，与本地文档 6,000 不一致；`moneyflow_cnt_ths` MCP 描述为 4,000，与本地文档 5,000 不一致。MCP 工具 schema 未暴露 `limit/offset`。因此现有证据不能冻结生产分页行为。

P0 必须补齐七接口不传业务参数、只传对象过滤（大盘不适用）、时间点、时间区间和分页验证；优先 MCP，分页缺口使用经确认的现有 SDK 只读验证补齐，不安装依赖。记录显式参数、响应字段、页大小、offset、末页、重复/漏键、字段精度及权限限流。不能以文档或 SDK 能接受参数代替真实分页结论。

## 3. 总体链路与分层

```text
首次历史：Prod raw_tushare 七表
          → 有界只读导出 → staging 中间文件
          → DuckDB 按交易日生成 Raw 候选 → 校验和逐文件提升
          → Silver 候选 → 校验和逐文件提升
          → 文件对账通过 → 分区注册及 runless 事件补录

持续新增：DG 交易日分区 → 独立 Raw 日更 job → Tushare 完整分页
          → Raw 候选及 blocking checks → 正式 Raw
          → Silver 日更 job → 标准化候选及 blocking checks → 正式 Silver
```

历史和日更生成同一份字段、身份和路径合同；仅来源证明不同。业务字段不携带 `api_name`、`fetched_at`、`raw_payload`、`created_at`、`updated_at` 或融合 `source` 字段。bootstrap 来源、冻结批次、行数及校验摘要记录在运行报告和 DG metadata。

Raw 不按当前上市池、激活池、价格或金额为零筛行。Silver 只做日期和明确的存储标准化，保留来源金额单位、NULL、所有选定业务字段与有效行；不融合七接口，不重算源净额。暂不建立下游查询契约。

## 4. 字段与身份合同

### 4.1 两层统一字段清单

以下为明确投影；请求字段、Prod COPY 投影、Parquet 列顺序和 definition schema 必须对账。代码中 schema 统一登记在 `defs/run_contracts/asset_column_schemas.py`，请求字段从该合同派生，不再维护一份独立字段清单。

| 数据集 | 选定字段，按顺序 |
| --- | --- |
| `moneyflow` | `ts_code, trade_date, buy_sm_vol, buy_sm_amount, sell_sm_vol, sell_sm_amount, buy_md_vol, buy_md_amount, sell_md_vol, sell_md_amount, buy_lg_vol, buy_lg_amount, sell_lg_vol, sell_lg_amount, buy_elg_vol, buy_elg_amount, sell_elg_vol, sell_elg_amount, net_mf_vol, net_mf_amount` |
| `moneyflow_dc` | `trade_date, ts_code, name, pct_change, close, net_amount, net_amount_rate, buy_elg_amount, buy_elg_amount_rate, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate` |
| `moneyflow_ths` | `trade_date, ts_code, name, pct_change, latest, net_amount, net_d5_amount, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate` |
| `moneyflow_ind_dc` | `trade_date, content_type, ts_code, name, pct_change, close, net_amount, net_amount_rate, buy_elg_amount, buy_elg_amount_rate, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate, buy_sm_amount_stock, rank` |
| `moneyflow_ind_ths` | `trade_date, ts_code, industry, lead_stock, close, pct_change, company_num, pct_change_stock, close_price, net_buy_amount, net_sell_amount, net_amount` |
| `moneyflow_cnt_ths` | `trade_date, ts_code, name, lead_stock, close_price, pct_change, industry_index, company_num, pct_change_stock, net_buy_amount, net_sell_amount, net_amount` |
| `moneyflow_mkt_dc` | `trade_date, close_sh, pct_change_sh, close_sz, pct_change_sz, net_amount, net_amount_rate, buy_elg_amount, buy_elg_amount_rate, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate` |

### 4.2 存储类型与数值语义

Raw `trade_date` 为 `VARCHAR`，固定 `YYYYMMDD`；Prod `DATE` 按相同表示导出。Silver 改为 `DATE`，分区 key 均为 `YYYY-MM-DD`。Hive 目录列不当作文件物理列，查询使用明确投影。

身份、名称和分类为 `VARCHAR`；普通资金流的量字段为 `BIGINT`；`company_num/rank` 为 `INTEGER`。金额采用 Prod 对应模型的 `DECIMAL(20,4)`（普通资金流）或 `DECIMAL(24,4)`（其余资金流）；价格/指数和涨跌幅分别按对应模型 `DECIMAL(18,4)`、`DECIMAL(10,4)`，其中 `moneyflow_cnt_ths.industry_index` 按现行模型为 `DECIMAL(24,4)`。P0 对照真实列精度与源样本后逐列冻结，禁止强制四舍五入来消除源精度差异。

CSV 金额以十进制文本导出，再由 DuckDB 显式转换；禁止经 Python float 中转 Prod NUMERIC。Tushare 返回值使用十进制转换和精度损失检查；NULL 不变成 0，NaN/无穷不能进入正式数值列。超出精度或类型不可表达时停止，不自动扩 schema。

普通个股、DC 个股、THS 个股金额单位为万元；DC 板块和大盘为元；THS 行业和概念为亿元。普通个股量单位为手。定义字段说明逐列写明原单位及 NULL，净流入允许负值。DC/THS 的 `buy_*_amount` 可表示该档净流入，不等同普通 `moneyflow` 的买入总金额；不强加净额等于分档之和、流入减流出严格相等或涨跌幅不超过 100% 的规则。

### 4.3 身份与历史代码

| 数据集 | Raw / Silver 唯一身份 | 特别约束 |
| --- | --- | --- |
| `moneyflow`、`moneyflow_dc`、`moneyflow_ths` | `trade_date + ts_code` | 保留历史代码及北交所真实响应，不按现上市集合过滤 |
| `moneyflow_ind_ths`、`moneyflow_cnt_ths` | `trade_date + ts_code` | 不按当前行业或概念目录裁剪历史 |
| `moneyflow_ind_dc` | `trade_date + content_type + name` | 保持现行 Raw 身份；`ts_code` 允许为空，不按代码去重或按名称反查补码 |
| `moneyflow_mkt_dc` | `trade_date` | 每个就绪交易日恰一行 |

相同 key 的完全重复和冲突重复都报出原因并阻断，不用静默去重掩盖分页或归一化问题。东财板块代码为空、一个代码对应多名称等情况作为诊断保留；不能未经历史全量身份审计就改用代码主键。名称作为身份时不做会改变 key 的 trim/别名替换；仅验证是否为非空有效字符串。Silver 不新增推测代码、行业层级或生命周期字段。

## 5. 资产、分区与路径

每个业务数据集对应一个 Raw 和一个 Silver，共 14 个物理资产。下表 `d` 只用于说明命名规则，实际登记必须展开为七个明确条目。

| 对象 | 拟定命名 |
| --- | --- |
| Raw asset | `raw_tushare_{d}` |
| Silver asset | `silver_{d}` |
| Raw / Silver job | `raw_tushare_{d}_update_job` / `silver_{d}_update_job` |
| 数据更新 sensor | 对应 `job` 名加 `_sensor` |
| 专属动态分区 | `cn_a_{d}_trade_days`，同数据集 Raw/Silver 共用 |
| 分区注册 sensor | `cn_a_{d}_trade_day_sensor` |
| Raw check | `raw_tushare_{d}_file_contract_check` |
| Silver check | `silver_{d}_standardization_check` |
| Catalog partition model | `trade_date_partition_raw_{d}` / `trade_date_partition_silver_{d}` |

拟定路径：

```text
/Volumes/datasource/data_lake/raw/tushare/{d}/trade_date={YYYY-MM-DD}/part-000.parquet
/Volumes/datasource/data_lake/silver/moneyflow/{d}/trade_date={YYYY-MM-DD}/part-000.parquet
/Volumes/datasource/data_lake_staging/moneyflow/{operation_id}/{d}/...
```

正式路径函数进入现有 `defs/paths.py`，通过 `lake_path` 生成，不新增湖根或把 `raw_tushare` 用作 Lake 目录。Raw/Silver 均登记现有 `LAKE_ASSET_CATALOG`，分组采用 `moneyflow`；标签复用 `DataDomain.QUOTE_DATA`，不为本专项扩充全局域枚举。中文名称、schema、check 名和路径逐条一致。

分区权威日期取已就绪的正式交易日历；动态分区只表示注册状态，不证明文件存在或源数据完成。每个数据集起点及 bootstrap 截止 `C_d` 由 P0/历史 plan 冻结，不把样本边界直接写成七数据集固定连续历史合同。历史范围内的缺日、非交易日记录及合法晚起数据分别列清；异常处理未确认前，不丢行也不补绿事件。

Silver 真实依赖同日对应 Raw，七条资金流之间无执行依赖；不伪造与 `dc_index/dc_daily` 的资产依赖。若 P0 证明覆盖检查需要具体基础资产，作为 check 的实际输入在 LLD 单独列清，不把上游资产混入日更 job selection。

## 6. 历史 bootstrap：先文件，后事件

### 6.1 冻结来源计划

计划按数据集列出：投影/schema、来源日期集合、业务键、缺日与异常、截止 `C_d`、来源计数/摘要、导出 unit、连接/SQL 数、目标冲突、候选及正式文件数、磁盘空间、预计时间和预算。所有日期和字段标识符来自受控七表合同；值绑定或由严格日期/key builder 生成。

东财板块历史按 Prod 实际 `(trade_date, content_type)` 集合与每类行数冻结，不要求早期每个日期已经具备后来出现的全部类型，也不把当日 496/504/31 固定成历史期望数。全日缺失、某类尚未起始和来源漏采必须经 P0 分开确认；未解释的缺失保持阻断，不能把日更三类型规则回放成历史删行或补零规则。

本机人工 Prod 只读查询和导出遵守 `AGENTS.local.md`，统一通过已有 `bash scripts/psql-remote.sh -f <受控SQL文件>`。SQL 使用 `BEGIN READ ONLY`、有界 timeout、显式字段 `COPY (SELECT ...) TO STDOUT`，输出直接进入 staging 文件，不进入日志；完成后回滚。不得读取另一份 env、直接拼连接串或新建直连旁路。该脚本源码不修改。

DG `ProdPostgresResource` 虽已有只读能力，本方案不据此绕过本机唯一访问入口。若以后需要把 bootstrap 改为 resource 内直接流式读取，必须先明确解决本机入口规则与该执行方式的边界，再修改原方案；本轮不默认授予这个例外。

### 6.2 读取与写分区分开

- 六张有日期索引的表：按有界日期窗导出，初始窗口上限 20 个交易日，再按行数预算缩小；每个 unit 一个连接和只读事务，不逐日重复连接。
- `moneyflow`：只有 `(ts_code, trade_date)` 索引。以有序业务键进行 keyset 分块导出，每块最多 100,000 行，不使用深 OFFSET 或按日反复扫全表。P0 用 EXPLAIN 验证读取计划；截止日期过滤、排除的后续数据量和索引扫描成本都要入报告，不能把 keyset 自动等同于无扫描成本。
- 每个导出 unit 先生成只读来源中间文件并记录 SHA-256、行数、key 边界和 schema。Python 管理进程、计划和摘要；DuckDB SQL/COPY 按日期生成列式候选，不用 Python 逐行插入大表。
- `moneyflow` 的同日数据会来自多个代码块。全部相关块完成后，按年份批量读取这些中间文件、一次组织年份内日期候选，避免“每个日期扫描全部导出块”。单日最终候选未完整时不能提升。
- 按 unit 对来源计数/摘要与导出文件核验，并用一次分批复核查出源数据在导出期间发生的变化。没有全历史长事务；变化的 unit 作废并重导，不能宣称跨多个事务的全库一致快照。

### 6.3 候选、提升与续跑

候选全量校验 schema、日期、key、类型精度、源/目标行数和排序后的业务内容摘要，再逐文件 `os.replace()`。执行前确认 staging 与目标 `st_dev` 相同；不相同则停止，不用复制到正式目录伪装原子操作。

checkpoint 按来源 unit、Raw 文件、Silver 文件分别记录完成事实和 hash。续跑先读回已完成文件，验证其与计划/候选一致，再跳过；源合同、计划或文件内容变化时停止。目标已有相同 hash 时可幂等跳过，已有不同内容时默认冲突停止；覆盖必须单独给出精确分区清单。

取消在 unit 前后、日期候选生成和文件提升前检查。保留已完成正式文件和 checkpoint，未完成的候选不能被当作正式数据；不自动删除异常现场、不使用 Kopia 或备份/快照。多文件不承诺整体原子性，Raw 已完成而 Silver 未完成时下游保持未就绪。

### 6.4 历史事件

历史使用“直写文件 + runless 补录”，不是为每个日期创建 Dagster backfill run。文件阶段和事件阶段独立批准、独立对账。

文件对账全历史通过后，按不超过 100 个日期的批次注册真实分区并补 materialization，metadata 指向已核验文件和 bootstrap 来源证明。已有同内容事件跳过；文件不存在、校验失败或 hash 不匹配时不得补成功事件。

全历史物理检查必须完成，但默认只补每数据集最近最多 20 个已完成日期的 Raw/Silver check events，最多 280 条。更早日期保持历史物理审计证据，不伪造 check event；是否扩大事件补录另行评估。历史物理完整、materialization 存在、正式 check event 存在分别报告。

## 7. Tushare 日更与来源完成判断

### 7.1 请求合同

七接口按单日请求，`trade_date=YYYYMMDD`，显式传全部选定字段及经 P0 核验的 `limit/offset`。`moneyflow_ind_dc` 依次展开行业、概念、地域，三类全部完成后才构成同日候选。其他接口不默认按代码循环，也不从生产对象池获取请求范围。

初始拟采用 `page_size=2,000`，以避开已知上限冲突；这只是待验证设计值。必须证明 limit 被遵守、offset 推进有效、末页可终止、页间无重复/漏键。复用 `execute_bounded_pages` 的短页/空页终止、跨页重复检测和累计预算，不能调用 `drop_duplicates` 修补源分页错误。

首次日更切换逐数据集冻结 `C_d`，从其后首个 expected trade date 接续；bootstrap 期间新到达的日期不随历史冻结计划漂移。切换前做日期集合差集，明确历史终点、待接续窗口和已完成目标，避免停用 bootstrap 后遗失中间数日或与日更重复写同一分区。

现有 helper 每次调用建立独立预算；东财三类型调用不能各领一份“单日预算”。外层必须累计请求、重试、行数及耗时，并把剩余预算传入下一类。字段或契约错误不重试；短暂网络与限流按现有分类有限退避。分页未结束、任一类失败/未尝试、超预算或响应无 schema，整日失败并保留候选，不能产生 ready 结果。

### 7.2 成功不等于非空

P0 必须分别确定七接口的有效证券/板块覆盖与源完成判断。不能把以下条件单独当作完整证明：行数大于零、时钟到 21:30、短页终止、两次摘要一致、与前一日行数接近，或与 Prod 当日行数相等。

拟定源稳定证据为两次完整读取的 key/业务摘要一致；稳定间隔和跨日修订样本由 P0 冻结。它只能证明观测稳定，不能证明源未遗漏。若使用同日股票日线、证券生命周期或板块目录作覆盖证据，必须先实测其与该接口的范围差异：普通/DC/THS 个股观察到的行数不同，不能套用一条集合相等规则；行业/概念目录也不能用当前集合裁剪历史。

LLD 必须写清每接口能够证明的范围、无法证明的源端最终性、阻断与人工复核条件。若某接口只能取得局部响应且没有可接受的覆盖/完成证据，该接口不能进入自动化阶段；不能新增 Prod 日常门禁或静默降低质量要求绕过。

## 8. 自动化、唯一 writer 与 readiness

建议日更可尝试窗口从上海时区 21:30 开始，sensor 最小间隔 600 秒；次日继续补尚未就绪日期。时间只控制请求时机，不作为完成证据。每个更新 sensor 最多查看最近 10 个 expected trade dates、每 tick 最多提交一个分区；更早缺口进入人工历史修复，不让热路径追全历史。

先检查时间窗、calendar、同资产 active run、已完成候选及 bounded readiness，再决定是否发 run。source readiness 仅做经 P0 认可的轻量时机探测；完整采集和稳定性核验放 writer run，sensor 不写 Parquet、不循环拉全市场分页。

缺文件可有限尝试；已有文件但 blocking check 失败或文件/metadata 摘要不匹配时阻断，不自动覆盖。已就绪日期默认不重写；源端后续修订以有限诊断发现并交人工明确的修复范围，不把“回看”变成自动重刷历史。

Raw 成功且同日当前 check 通过后才触发对应 Silver。readiness 采用当前文件、关联该内容的 materialization/check 证据及同日 Raw 依赖；窗口查询必须真正批量，复用正式 check SQL，一次 tick 最多一个 DuckDB connection，不读取全历史事件或把旧 check 绑定到新文件。历史早期 check 未补录不代表物理数据缺失，也不能冒充当前事件 ready。

每个 `(asset, partition)` 只有一个 writer；统一 run key builder、active-run 排他、目标旧 hash 比较及文件提升前再次复核，共同防重复触发。bootstrap 与日更不能同时写同一数据集；正式 bootstrap 期间本族 sensor 保持 STOPPED，操作结束后重新做当前源/目标边界审计。

七个 Raw 日更拟用容量 1 的专属执行池串行请求，Silver 单独处理。该池只限制本族，不代表整个 Tushare token 已全局限流；P0 必须审计其他 DG/Prod 任务的 token 配额竞争和现有并发配置。未核清时，不启用自动化，不调整其他任务或新建全局限流服务。所有新 sensor 默认 STOPPED。

## 9. 检查、可观测性与失败语义

每个 Raw 一个 partitioned blocking `file_contract_check`，覆盖明确文件合同：schema/精度、分区日期、唯一身份、字段有效性、分类展开闭合、文件与来源证明的行数/摘要。每个 Silver 一个 partitioned blocking `standardization_check`，覆盖标准化合同：DATE、身份、源字段/单位不变、无损转换、与同日 Raw 的内容及计数对账。复杂公式由金样本测试验证，不为本专项新增指标计算。

分类闭合按来源阶段的已冻结合同验证：bootstrap 核对实际 Prod 分类集合；日更核对三类请求及 P0 确认的合法空/非空语义。来源阶段不能由任意可编辑的宽松开关指定，必须来自受控 bootstrap 证明或当前日更 writer 的完成证据；两者共用身份/schema 规则，不保留两份业务校验实现。

普通文件质量以正式 blocking checks 承载；候选提升使用编码规范允许的 schema/读回/完整性校验，不在 asset 函数复制第二份业务 guard。writer source closure、候选检查和正式 check 共用底层合同与 SQL。Dagster materialization 可能早于正式 check；只有当前 check 与 readiness 通过，才称为可消费成功。

源空结果且保留 schema，仍只是“源暂未提供数据”，除非 P0 明确证明该数据集/日期允许空分区，否则不发布空文件或成功事件。大盘有效日期必须一行；NULL 金额、负净额、零成交和高涨跌幅依本字段合同处理，不任意删除。

definition metadata 固定中文字段 schema、单位、来源文档、路径、分区和合同版本；materialization 记录本次路径、行数、observed columns、来源方式、请求/页/重试/拒绝数、摘要、upstream batch ID 和阶段耗时。source proof 的完整明细留报告，cursor 只保留紧凑原因与有限样本，复用现行 v1 builder；不新增状态表、summary asset、readiness asset 或隐藏 catalog。

长任务每个完成 unit/page 和至少每 30 秒输出阶段、日期/key 窗口、完成量/总量、耗时和最后更新时间。ETA 未测准时显示“暂无法估算”。拒绝记录说明 reason code、最多 20 个样本及差异数量，身份、类型、分页错误整分区阻断，不把大量 reject 当作正常损耗。状态/事件写入失败不删除或回滚已提升的数据文件，恢复时按物理 hash 幂等补事件。

## 10. 性能模型与拒绝策略

以下是设计预算，尚未通过实测验收。源端单日基线为 18,320 行；按 2,000 行页大小、三类展开，单轮理论约 16 页，若某 scope 恰好整页还需终止页。两轮稳定性读取约 32 次，不含轻量探测/重试；这些数值不能替代真实分页测量。

| 项目 | 初始设计边界 | 超预算处理 / 准入证据 |
| --- | --- | --- |
| 单日对象与枚举 | 七接口；东财板块三类；不按证券池展开 | 新增类型/代码循环先改方案与请求成本 |
| API 单页 | 2,000 行；每数据集单日最多 20,000 行 | P0 验证限量；超限停止，不截断 |
| 单日 API 总预算 | 每数据集最多 64 次实际请求、300 秒，含两轮、三类和重试 | 所有 scope 累计；超限失败并保留候选 |
| 限流 | 本族并发 1；最小请求间隔 1 秒；最多 3 次重试，退避复用 helper | 审计 token 共享配额；不能把局部 limiter 称全局限流 |
| 日更内存 | 当前页列式接收，Python 缓冲最多两页；身份集合最多 20,000 key | `consume_page` + `retain_rows=False`；测峰值 RSS |
| Prod 导出 unit | 六表最多 20 个交易日且不超过 100,000 行；普通资金流 keyset 最多 100,000 行 | 计划估算/读回超限则拆小 unit，不扩大窗口 |
| Prod 事务与连接 | 每 unit 一个只读事务/连接；SQL 执行预算初始 120 秒 | P0 测查询计划与吞吐；超时停止，不换 host/权限盲重试 |
| DuckDB scan/write | 小表按日期窗；普通资金流按年批量分区，禁止日数×全量块重复扫描 | 记录读文件数、scan 字节、候选数量和最慢阶段 |
| DuckDB 内存与 spill | 复用现行连接策略/既有目录；每批 Python 峰值 RSS 目标不超过 512 MiB | 不新增临时 env 调参；LLD 给出 scan、join、write、spill 上界 |
| 提升粒度 | 单文件；单日每层一文件，每次生成最多 20 个日期候选 | 逐文件 checkpoint；不称多文件事务 |
| 磁盘 | 来源中间文件 + 未提升候选 + DuckDB spill + 安全余量 | P0 测每百万行字节数，按实际空间计算；不足不启动 |
| sensor | 每资产最多 10 日、每 tick 一个 run；摘要 cursor 目标 <2 KiB、硬上限 8 KiB | 超预算阻断；不全历史深扫 |
| 历史事件 | materialization 预计 `2 × ΣD_d`；check events 默认 ≤280 | D_d 为实际可导入日期数；按100日期分批，禁止全历史逐分区深 readiness |

bootstrap 总耗时按“导出字节/实测速率 + 转换字节/实测速率 + 文件数×提升开销 + 事件数/实测速率”分别估算；连接/SQL 次数按导出 unit 数计，至少加一次分批来源复核。历史文件数为 `2 × ΣD_d`，不把七数据集视为同起点。全量字节、日期数、SQL 次数、网络耗时、磁盘峰值和 spill 尚未测量，P0/P3 plan 没有填写完整前禁止全量 apply。

## 11. 参数与配置审计

新参数尚未实现。来源、作用范围与消费者集中如下；LLD 展开实际符号/测试，不允许在脚本、页面、sensor 各自写一套值。

| 参数组 | 拟定值 / 来源与持久化位置 | 消费者与生效方式 |
| --- | --- | --- |
| 七表/接口/字段/身份/单位 | 本文及既有源文档；DG schema 与 `run_contracts/moneyflow.py` 的稳定合同 | 请求、bootstrap、writer、check、catalog；代码发布/reload 生效 |
| page/row/request/elapsed/retry | §10 设计值，P0 实测后确认；同一稳定合同 | Raw source/writer；必须测试三类型和两轮累计预算 |
| 时间窗、tick、回看窗口 | 21:30、600秒、10日，P0确认；同一稳定合同 | 分区/更新 sensor；上海时区，默认 STOPPED |
| 本族执行池 | 拟定 `moneyflow_tushare_writer`、容量1；asset合同和正式 instance 已有并发配置机制 | 七 Raw jobs；启用前审核实际配置，不改其他池 |
| Lake/staging 根 | 复用现有 `paths.py`，不新增 env | 路径、writer、bootstrap；挂载/同文件系统/冲突测试 |
| DuckDB 设置 | 复用现有连接设置与环境，不加专项默认值 | 列式转换和检查；测量实际策略、目录与 spill |
| Tushare 凭据 | 复用当前 `TushareResource` 的 token 来源，不新增 token/env | 日更与来源验证；只报告是否可用，不输出值 |
| Prod 凭据与入口 | 复用 `scripts/psql-remote.sh` 与 `.env.web.local`；不得带入新配置或报告 | 人工只读 audit/bootstrap，schema/table/field白名单测试 |
| bootstrap 执行输入 | 明确 dataset、日期/key范围、operation ID、冻结 plan、批次上限；存 plan/checkpoint | 仅人工 CLI；不得把连接串、任意 SQL或覆盖开关当自由输入 |

源可选参数不自动成为运营控件。本次正式日更只需要分区日期；不增加 Ops 配置表、Web 页面或生产 schedule。预算修改必须同步本文、LLD、合同和反例测试。

## 12. 实施落点与影响面

拟定新增职责按域集中，不在本轮创建代码文件：

| 位置（相对 `lake_console/orchestrator/src/orchestrator/`） | 职责 |
| --- | --- |
| `defs/run_contracts/moneyflow.py` | 请求/身份/预算/命名合同；不复制 asset catalog |
| 现有 `defs/run_contracts/asset_column_schemas.py`、`defs/paths.py`、`defs/partitions.py` | 七数据集 schema、路径、专属分区 |
| `defs/source_readiness/moneyflow.py` | 时机与来源稳定/覆盖证据职责，不能写湖 |
| `defs/io/moneyflow_raw_writer.py`、`defs/io/moneyflow_silver_writer.py` | 有界源接收、列式候选及合同校验/提升 |
| `defs/assets/moneyflow.py`、`defs/checks/moneyflow.py` | 14资产与14 partitioned blocking checks |
| `defs/jobs/moneyflow.py`、`defs/sensors/moneyflow.py` | selection、typed config、分区注册、日更/阻断、紧凑cursor |
| `defs/asset_guards/moneyflow_readiness.py` | 复用正式 check SQL 的有界批量 readiness |
| `defs/bootstrap/moneyflow_history.py` 及职责明确的 CLI / event 模块 | 受控 COPY、plan、checkpoint、分批候选/提升及独立事件补录 |
| 现有 catalog、中文名映射、tags 与相关配置登记 | 对账新定义；不扩充来源和业务域 |
| 项目 `tests/` | 来源、身份、分页、类型、检查事件、预算、恢复与负向静态门禁 |

已使用 `codegraph_explore` 分析资金流模型、`moneyflow_publish` 调用关系、Prod 与 DG 入口，并核验 `execute_bounded_pages` 源码和调用方。共享分页策略已有其他资产/初始化消费者，新接入只复用，不改变它们的默认值、方法签名和行为；若发现复用不满足累计预算，先在资金流调用层设计闭合，不改通用契约掩盖问题。

当前 Biz 大盘资金流消费者读取 `MarketMoneyflowDc`，板块消费者读取 `BoardMoneyflowDc`；本次不改这些模型/视图/API、前端或 Prod DatasetDefinition。DG catalog禁止导入生产 DatasetDefinition生成本族定义，schema手工实施后通过对账测试维护与已批准字段一致。新增资产属于独立 Orchestrator，不新增 foundation/ops/biz 反向依赖，也不改变仓库依赖矩阵。模块边界和主入口未改变，不更新 CodeGraph 架构快照。

仍需人工/真实证据确认的边界：七接口最终分页与范围、历史异常分类、每日覆盖证据、token 全局竞争、实际日期截止、空间与吞吐、唯一 writer/维护窗口和正式事件量。不能由 CodeGraph 或文档检查代替。

## 13. 分阶段计划与验收

| 阶段 | 交付内容与退出条件 | 执行边界 |
| --- | --- | --- |
| P0 来源与合同核验 | 七接口规定参数/字段/分页实测；Prod投影、精度、索引、缺日、身份与预算；完成逐数据集7A/LLD、配置审计及Go/No-Go | 只读来源动作按规则；不写正式Lake/事件，不因缺依赖安装 |
| P1 小规模数据集能力 | 先大盘、THS行业/概念，再DC板块；每个数据集独立Raw/Silver、check、隔离fixture验收 | 一轮一个明确数据集/切片；不顺手七数据集一起改 |
| P2 三个个股能力 | 按相同合同逐个实施普通/DC/THS个股，补股票范围、全字段精度、分页压力测试 | 共享能力先做语义审计；不改Prod入口 |
| P3 历史工具与文件验收 | 实现有界plan/export/重分区/checkpoint；故障/幂等隔离测试；获批单日期样本后分批正式bootstrap及全范围对账 | 正式写湖单独批准，冻结精确命令、日期、读写范围和冲突处理 |
| P4 DG事件与编排 | catalog/job/sensor及实际分区check事件测试；文件通过后补注册/materialization/最近checks | 正式definitions验证、分区与事件写入分别确认；sensor仍STOPPED |
| P5 日更切换验收 | 对每数据集从`C_d`后的expected date开始，最小真实采集/读回、失败重试/续跑，再观察至少3个自然交易日 | job执行、sensor启用另行批准；不启用Prod发布 |

编码前从本方案与LLD抽取“必须/禁止/默认/边界/验收”清单，逐条映射代码、正反测试和真实证据。阶段退出必须独立验收，不能因某个小表通过而将七数据集全部标完成。

最低验证矩阵：

- 只允许七接口/七表和投影字段；BIYING、stockdb、融合来源、内部字段、任意SQL与旧湖路径反例必须拒绝。
- 默认/显式/关键字段、无参数/对象/单日/区间、分页推进/末页、忽略limit、重复页、晚到数据、三类型缺失、两轮变化、网络/权限/限流及预算累计。
- 全字段精度与NULL金样本；负净额、零值、上市首日高涨跌幅、北交所与退市历史、板块空代码不能误删；代码/名称冲突不能静默去重。
- Raw/Silver只写自身selection；实际分区check的evaluation与存储partition归属一致；旧check/旧materialization不能绑定到新文件。
- 空源/坏schema/未完成分页/预算耗尽/目标冲突不得替换正式文件；中途取消、进程退出、checkpoint丢失/失配、同内容重放、并发writer、跨文件部分完成和事件写失败均可解释恢复。
- 临时文件/隔离instance完成上述测试；真实样本分别记录源端、导出、归一化、reject及原因、候选、正式读回数量和内容摘要。
- 性能测量包括请求/页/重试数、连接/SQL/scan数、p50/p95/最慢阶段、RSS/spill、字节/文件/事件数量、总耗时；无上界或超过预算即停止设计复审。

历史缺口报告保持真实：bootstrap只迁移已冻结的Prod历史事实，不自动改从Tushare重抓缺口；若需补缺必须单独确认日期和来源。当前已完成事实迁移也不等于“2010年至今所有七数据集无缺日”。

## 14. 交付与本版完成状态

本版完成：七数据集/来源范围、审计基线、字段投影、原单位与身份、两层拓扑、路径/命名、来源切换边界、历史导出与恢复、日更闭合要求、拟定性能/配置预算、实现影响面和验收阶段。

本版未完成：P0分页与源完成证据、全历史覆盖/身份/精度复核、实际bootstrap规模和耗时、LLD、代码与隔离测试、正式文件/事件写入及sensor启用。技术方案完成不意味着这些实施门禁通过；下一步是评审本文，然后按批准的P0范围补证据并冻结LLD。

本轮只新增本文及主索引链接；不修改生产API/CLI、DatasetDefinition、资源配置、DG definitions、数据库或Lake。方案采用现行路径与单向依赖，不调整依赖矩阵。主要风险是来源分页/最终性、历史缺口和板块身份、普通资金流导出成本与共享token配额；均已映射至相应阻断条件与验收阶段。
