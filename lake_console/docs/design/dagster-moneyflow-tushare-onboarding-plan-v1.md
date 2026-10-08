# Dagster 七个 Tushare 资金流向数据集接入技术方案 v1

> 状态：2026-10-07管理员已确认七表历史统一按日期批次读取，直接生成每日Raw/Silver候选，取消代码keyset导出和spool，当前方案及新P3步骤见§6、§10、§24。P0/P1/P2既有来源与候选验收保留；旧历史代码已迁移为日期批次直接生成候选，隔离验收见§25；2026-10-08真实Prod日期查询及内存接收结果见§26。普通moneyflow日期索引已获准在Prod建成并通过同批次复测，见§27；§22～23保留旧实现记录。正式历史bootstrap、DG资产/事件及自动化尚未执行。
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

管理员再次明确：上表是七个独立数据集，每个接口单独对应一个数据集，不建设一个包含七个来源的资金流数据集。每个数据集各自拥有Raw/Silver、专属分区、job、sensor、check和来源证明；资金流分组及共用工具只用于组织与复用，不合并业务记录或运行状态。Tushare请求配额由管理员确认充足，不再作为P0待核事项或阻断项。日更每天上海时间22:00触发登记当天partition；登记仍使用现行交易日历校验，不代表数据已采集或检查成功。

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

初次审计发现 `moneyflow_dc` 可返回 6,024 行，MCP 描述为 8,000，与本地文档 6,000 不一致；`moneyflow_cnt_ths` MCP 描述为 4,000，与本地文档 5,000 不一致。MCP 工具 schema 未暴露 `limit/offset`，当时尚不能冻结分页。P0 已用现有 SDK 实测 DC 默认返回8,000行、THS概念默认返回4,000行，并补齐2,000行分页证据，见下节。

P0 必须补齐七接口不传业务参数、只传对象过滤（大盘不适用）、时间点、时间区间和分页验证；优先 MCP，分页缺口使用经确认的现有 SDK 只读验证补齐，不安装依赖。记录显式参数、响应字段、页大小、offset、末页、重复/漏键、字段精度及权限限流。不能以文档或 SDK 能接受参数代替真实分页结论。

### 2.3 P0 第一轮实测回填（2026-10-06）

完整证据见[P0核验与实施合同](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-p0-contract-audit-v1.md)。以下精确统计对应只读冻结范围 `2010-01-01..2026-09-30`，替代§2.1估算用于后续规模规划；范围外记录尚未统计。

| 数据集 | 日期数 | 精确行数 | SSE日历整日缺口 |
| --- | ---: | ---: | --- |
| `moneyflow` | 4,067 | 14,089,300 | 无 |
| `moneyflow_dc` | 739 | 4,278,673 | 2023-11-22 |
| `moneyflow_ths` | 431 | 2,191,645 | 2026-07-06、07-09 |
| `moneyflow_ind_dc` | 739 | 364,012 | 无 |
| `moneyflow_ind_ths` | 494 | 44,460 | 2024-11-04、2025-01-20、2026-07-09、08-05 |
| `moneyflow_cnt_ths` | 495 | 192,009 | 2024-11-04、2025-01-20、2026-07-09 |
| `moneyflow_mkt_dc` | 839 | 839 | 2026-07-09 |

合计21,160,938行、7,804个数据集日期，业务键无重复，范围内未见非交易日记录。11个数据集日期缺口中，6个当前源端非空，5个当前源端也空；后者不能直接认定合法空分区。THS个股首三个日期各2行，DC个股2026-05-19仅2,812行；日期存在不等于证券覆盖完整。DC概念/地域从2025-02-26开始，早期只有行业，历史规则保持按实际分类迁移。

09-30七接口两轮分页共32次请求，18,320行业务键及选定字段与Prod逐行一致；2,000行页大小和显式类型可用于实现设计，自动化仍需P5真实日更验收；源端最终性无法从两个历史轮次保证。100,000行普通资金流导出用22.673秒，临时Raw/Silver转换和读回均100,000行、业务差异0，峰值RSS约190MiB。当时旧路线估计337个导出unit，后按年界拆分为347；这些代码块数量/吞吐不用于当前日期路线。当前423日期批次见§24/LLD§4，15,608个预计两层文件不变，直接生成/文件提升/全量耗时未验收。历史仍忠实复制Prod；不自动将6个可取得缺口改为Tushare历史补录。

按管理员补充问题，已核验DC个股汇总大盘及THS个股汇总行业/概念的可行性：DC多日金额汇总未精确匹配且缺少指数与占比所需信息；THS净额不能唯一还原流入/流出，当前成员也不能证明历史成员。两条样本的个股净额汇总与源板块净额存在差异，不能据此回填Raw。大盘2026-07-09完整源记录已再次读取成功，优先讨论直接补源接口缺口。细节见[P0报告§8](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-p0-contract-audit-v1.md#8-个股数据能否生成缺失大盘ths板块2026-10-06补充只读核验)；未新增派生合同或改变历史来源范围。

管理员随后确认：源端无法取得且不能可靠计算还原的历史缺口可以接受；保留来源报告中的真实缺失，不造值、不写空成功分区。此类已核验缺口不再要求补出数据作为P0通过条件；源端有数据但Prod漏采的情况仍须区分，正式历史补录另行冻结范围并批准执行。补查THS个股2024-12-19源端也只有2条，DC个股2026-05-19则源端5,955条、Prod2,812条，后者需要逐代码对账，见[P0报告§7.1](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-p0-contract-audit-v1.md#71-接受缺口后的补充核验与阶段澄清)。

## 3. 总体链路与分层

```text
首次历史：Prod raw_tushare 七表
          → 按日期批次只读读取 → 有界内存列式接收
          → 直接生成每日 Raw 候选 → 对应 Silver 候选
          → 同日期来源复核及候选校验 → 逐文件提升
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

Prod COPY传输中的金额保留十进制文本，仅在有界内存缓冲中由DuckDB显式转换，不保存来源CSV文件；禁止经 Python float 中转 Prod NUMERIC。Tushare 返回值使用十进制转换和精度损失检查；NULL 不变成 0，NaN/无穷不能进入正式数值列。超出精度或类型不可表达时停止，不自动扩 schema。

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

分区权威日期取已就绪的正式交易日历；动态分区只表示注册状态，不证明文件存在或源数据完成。每个数据集起点按P0实际来源边界，此次规划bootstrap截止 `C_d` 均固定2026-09-30；首次接续2026-10-08，执行前按冻结manifest复核而非随日期漂移。缺口仍显式保留，不表示连续无缺口。历史范围内的缺日、非交易日记录及合法晚起数据分别列清；异常处理未确认前，不丢行也不补绿事件。

Silver 真实依赖同日对应 Raw，七条资金流之间无执行依赖；不伪造与 `dc_index/dc_daily` 的资产依赖。若 P0 证明覆盖检查需要具体基础资产，作为 check 的实际输入在 LLD 单独列清，不把上游资产混入日更 job selection。

## 6. 历史 bootstrap：先文件，后事件

### 6.1 冻结来源计划

计划按数据集列出：投影/schema、来源日期集合、业务键、缺日与异常、截止 `C_d`、来源计数/摘要、导出 unit、连接/SQL 数、目标冲突、候选及正式文件数、磁盘空间、预计时间和预算。所有日期和字段标识符来自受控七表合同；值绑定或由严格日期builder生成，不接受代码范围。

东财板块历史按 Prod 实际 `(trade_date, content_type)` 集合与每类行数冻结，不要求早期每个日期已经具备后来出现的全部类型，也不把当日 496/504/31 固定成历史期望数。全日缺失、某类尚未起始和来源漏采必须经 P0 分开确认；未解释的缺失保持阻断，不能把日更三类型规则回放成历史删行或补零规则。

本机人工 Prod 只读查询和导出遵守 `AGENTS.local.md`，统一通过已有 `bash scripts/psql-remote.sh -f <受控SQL文件>`。SQL 使用 `BEGIN READ ONLY`、有界 timeout、显式字段 `COPY (SELECT ...) TO STDOUT`，业务输出进入有界内存缓冲，不落来源CSV文件、不进入日志；完成后回滚。每日Parquet候选直接生成在staging。不得读取另一份 env、直接拼连接串或新建直连旁路。该脚本源码不修改。

DG `ProdPostgresResource` 虽已有只读能力，本方案不据此绕过本机唯一访问入口。若以后需要把 bootstrap 改为 resource 内直接流式读取，必须先明确解决本机入口规则与该执行方式的边界，再修改原方案；本轮不默认授予这个例外。

### 6.2 按日期批次读取，直接生成每日候选

2026-10-07管理员确认：七表统一按日期读取，不再按股票代码导出后重新分桶。一个unit就是一个数据集的一批明确日期，也是候选生成和来源复核的批次；最多20个交易日、100000来源行，按年界拆分。日期批次可以含多日，但每条数据第一次生成Parquet时就进入所属日期，不先生成跨日期的来源数据文件。

- planner从冻结逐日计数生成日期集合；SQL仅过滤这一集合并显式投影批准字段。按trade_date和本数据集业务键排序；ts_code只用于同日排序/唯一性，不能作为遍历范围、分页游标或运营输入。
- 使用现行psql入口的COPY TO STDOUT，以64KiB块接收，单次传输缓冲不超过32MiB；DuckDB在有界内存中列式解析/校验，一次生成该批每日Raw候选，再从对应Raw生成Silver。Python只管理字节、进程、路径、预算和摘要，不逐业务行转换。不存在来源CSV落盘、年度spool或第二次重新归堆。
- 一个日期批次最多生成40个最终结构的Raw/Silver候选。正式路径与字段合同保持不变，保留staging中的候选、逐日来源证明和checkpoint。
- 保留一次独立来源复核：重新读取相同日期集合，在内存中与已生成Raw逐键逐字段对账，不生成第二份来源CSV或复核Parquet。这是正确性检查，不是再次分桶。两次读取不同则整批阻断，保留候选与有限差异证据；不自动接受新值或覆盖。
- 10月6日普通moneyflow只有代码领先索引的审计记录仍有效作为历史证据，但它不能推翻日期路线，也不能证明日期读取更快。新路线先核验实际索引和日期查询计划，实测单日及有界日期批次；超预算停止并重新评估，不自动改回代码导出、不自行新增Prod索引。

“一次生成”指每个日期批次直接产出每日候选，不是把全历史装入内存，也不是取消来源复核、候选校验或安全提升。具体读取、恢复和验收落点见LLD§19。

### 6.3 候选、提升与续跑

候选全量校验 schema、日期、key、类型精度、源/目标行数和排序后的业务内容摘要，再逐文件 `os.replace()`。执行前确认 staging 与目标 `st_dev` 相同；不相同则停止，不用复制到正式目录伪装原子操作。

checkpoint按日期批次、逐日来源证明、Raw文件和Silver文件分别记录完成事实与hash；不记录代码游标或spool阶段。续跑先读回已完成文件，验证其与计划/候选一致，再跳过；源合同、计划或文件内容变化时停止。目标已有相同 hash 时可幂等跳过，已有不同内容时默认冲突停止；覆盖必须单独给出精确分区清单。

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

独立 `execute_bounded_pages` 每次调用建立独立预算；东财三类型不能各领一份“单日预算”。P0 进一步确认当前 `BoundedCodePageRequestSession.execute_pages` 已支持共享 session 的多 scope 分页：每数据集日期复用同一 session，将三类型、两轮及重试纳入累计请求与耗时预算，资金流调用层另累计业务行数。字段或契约错误不重试；短暂网络与限流按现有分类有限退避。分页未结束、任一类失败/未尝试、超预算或响应无 schema，整日失败并保留候选，不能产生 ready 结果。

### 7.2 成功不等于非空

P0已把完成定义为显式请求完整结束、两轮观测稳定及存储合约通过；覆盖诊断不承诺源站无遗漏，逐接口规则见实施细则§2及七张卡。不能把以下条件单独当作完整证明：行数大于零、时钟到22:00、partition已登记、短页终止、两次摘要一致、与前一日行数接近，或与Prod当日行数相等。

拟定源稳定证据为两次完整读取的 key/业务摘要一致；间隔冻结60秒，窗口内每日最多一次修订复核；已有历史修订差异和源覆盖边界见实施细则。它只能证明观测稳定，不能证明源未遗漏。若使用同日股票日线、证券生命周期或板块目录作覆盖证据，必须先实测其与该接口的范围差异：普通/DC/THS 个股观察到的行数不同，不能套用一条集合相等规则；行业/概念目录也不能用当前集合裁剪历史。

LLD 必须写清每接口能够证明的范围、无法证明的源端最终性、阻断与人工复核条件。若某接口只能取得局部响应且没有可接受的覆盖/完成证据，该接口不能进入自动化阶段；不能新增 Prod 日常门禁或静默降低质量要求绕过。

## 8. 自动化、唯一 writer 与 readiness

管理员已确定：每天上海时区22:00触发七个独立数据集各自的当天partition登记，使用各自专属分区定义和现行交易日历。Raw更新链响应各自已登记的日期，不提前按21:30触发。partition登记只表示日期可运行，不作为文件或源数据完成证据。更新sensor保留最小间隔600秒、最近10个expected trade dates、每tick最多一个分区的有界补采设计；登记触发时间与后续失败重试分别处理。更早缺口进入人工历史修复，不让热路径追全历史。

先检查时间窗、calendar、同资产 active run、已完成候选及 bounded readiness，再决定是否发 run。source readiness 仅做经 P0 认可的轻量时机探测；完整采集和稳定性核验放 writer run，sensor 不写 Parquet、不循环拉全市场分页。

缺文件可有限尝试；已有文件但 blocking check 失败或文件/metadata 摘要不匹配时阻断，不自动覆盖。已就绪日期默认不重写；源端后续修订以有限诊断发现并交人工明确的修复范围，不把“回看”变成自动重刷历史。

Raw 成功且同日当前 check 通过后才触发对应 Silver。readiness 采用当前文件、关联该内容的 materialization/check 证据及同日 Raw 依赖；窗口查询必须真正批量，复用正式 check SQL，一次 tick 最多一个 DuckDB connection，不读取全历史事件或把旧 check 绑定到新文件。历史早期 check 未补录不代表物理数据缺失，也不能冒充当前事件 ready。

每个 `(asset, partition)` 只有一个 writer；统一 run key builder、active-run 排他、目标旧 hash 比较及文件提升前再次复核，共同防重复触发。bootstrap 与日更不能同时写同一数据集；正式 bootstrap 期间本族 sensor 保持 STOPPED，操作结束后重新做当前源/目标边界审计。

七个Raw日更拟用容量1的专属执行池串行请求，Silver单独处理；数据集与运行状态仍各自独立。管理员已确认配额充足，P0不再审计共享token额度或任务竞争，不以此阻止接入。现行调用超时、失败重试及本族资源上限继续保留，不调整其他任务或新建全局限流服务。所有新sensor默认STOPPED，按后续阶段批准启用。

## 9. 检查、可观测性与失败语义

每个 Raw 一个 partitioned blocking `file_contract_check`，覆盖明确文件合同：schema/精度、分区日期、唯一身份、字段有效性、分类展开闭合、文件与来源证明的行数/摘要。每个 Silver 一个 partitioned blocking `standardization_check`，覆盖标准化合同：DATE、身份、源字段/单位不变、无损转换、与同日 Raw 的内容及计数对账。复杂公式由金样本测试验证，不为本专项新增指标计算。

分类闭合按来源阶段的已冻结合同验证：bootstrap 核对实际 Prod 分类集合；日更核对三类请求及 P0 确认的合法空/非空语义。来源阶段不能由任意可编辑的宽松开关指定，必须来自受控 bootstrap 证明或当前日更 writer 的完成证据；两者共用身份/schema 规则，不保留两份业务校验实现。

普通文件质量以正式 blocking checks 承载；候选提升使用编码规范允许的 schema/读回/完整性校验，不在 asset 函数复制第二份业务 guard。writer source closure、候选检查和正式 check 共用底层合同与 SQL。Dagster materialization 可能早于正式 check；只有当前 check 与 readiness 通过，才称为可消费成功。

源空结果且保留 schema，仍只是“源暂未提供数据”，除非 P0 明确证明该数据集/日期允许空分区，否则不发布空文件或成功事件。大盘有效日期必须一行；NULL 金额、负净额、零成交和高涨跌幅依本字段合同处理，不任意删除。

definition metadata 固定中文字段 schema、单位、来源文档、路径、分区和合同版本；materialization 记录本次路径、行数、observed columns、来源方式、请求/页/重试/拒绝数、摘要、upstream batch ID 和阶段耗时。source proof 的完整明细留报告，cursor 只保留紧凑原因与有限样本，复用现行 v1 builder；不新增状态表、summary asset、readiness asset 或隐藏 catalog。

长任务每个完成 unit/page 和至少每 30 秒输出阶段、日期批次、完成量/总量、耗时和最后更新时间。ETA 未测准时显示“暂无法估算”。拒绝记录说明 reason code、最多 20 个样本及差异数量，身份、类型、分页错误整分区阻断，不把大量 reject 当作正常损耗。状态/事件写入失败不删除或回滚已提升的数据文件，恢复时按物理 hash 幂等补事件。

## 10. 性能模型与拒绝策略

以下为收尾设计预算；P0已实测单日18,320行，2,000行页大小、三类展开，每轮16页、两轮32次调用。分页样本已通过，整体执行预算尚未全部验收；若某scope恰好整页仍需终止页，轻量探测/重试和未来数据增长另计，不能将样本值当作固定请求数。

| 项目 | 初始设计边界 | 超预算处理 / 准入证据 |
| --- | --- | --- |
| 单日对象与枚举 | 七接口；东财板块三类；不按证券池展开 | 新增类型/代码循环先改方案与请求成本 |
| API 单页 | 2,000 行；每数据集单日最多 20,000 行 | P0 验证限量；超限停止，不截断 |
| 单日 API 总预算 | 每数据集最多 64 次实际请求、300 秒，含两轮、三类和重试 | 所有 scope 累计；超限失败并保留候选 |
| 请求节奏与失败重试 | 本族并发1；最小请求间隔1秒；最多3次重试，退避复用helper | 配额已由管理员确认充足；保留执行预算和错误处理，不新增共享配额审计 |
| 日更内存 | 当前页列式接收，Python 缓冲最多两页；身份集合最多 20,000 key | `consume_page` + `retain_rows=False`；测峰值 RSS |
| Prod 导出 unit | 七表统一按明确日期集合，每批最多20个交易日、100000行，按年界拆分 | 计划估算/读回超限则拆小 unit，不扩大窗口 |
| Prod 事务与连接 | 每 unit 一个只读事务/连接；SQL 执行预算初始 120 秒 | P0 测查询计划与吞吐；超时停止，不换 host/权限盲重试 |
| DuckDB scan/write | 仅解析当前日期批次；直接生成每日候选，不创建来源CSV/spool，不跨批次扫描历史来源块 | 记录读文件数、scan 字节、候选数量和最慢阶段 |
| DuckDB 内存与 spill | 复用现行连接策略/既有目录；每批 Python 峰值 RSS 目标不超过 512 MiB | 不新增临时 env 调参；实施细则冻结局部512MB/1线程/0spill，进程RSS拒绝线768MiB，单unit/窗口scan≤100000行，不修改全局连接设置 |
| 提升粒度 | 单文件；单日每层一文件，每次生成最多 20 个日期候选 | 逐文件 checkpoint；不称多文件事务 |
| 磁盘 | 每日Raw/Silver候选、正式新增输出、失败现场和控制文件；来源CSV/spool业务文件数为0，spill=0 | P0 测每百万行字节数，按实际空间计算；不足不启动 |
| sensor | 每资产最多 10 日、每 tick 一个 run；摘要 cursor 目标 <2 KiB、硬上限 8 KiB | 超预算阻断；不全历史深扫 |
| 历史事件 | materialization 预计 `2 × ΣD_d`；check events 默认 ≤280 | D_d 为实际可导入日期数；按100日期分批，禁止全历史逐分区深 readiness |

新路线按P0逐日计数试算为423个日期批次，初采+独立复核共846个读取事务；计划统计至多14个事务时连接基线860次。每事务BEGIN/SET/读取/ROLLBACK各一条，语句基线3440条；失败/恢复追加成本另计入同一个累计预算，完整APPLY计划必须冻结实际尝试上限。总耗时按“日期查询/传输实测 + 列式转换/候选校验实测 + 独立来源复核实测 + 文件提升 + 事件写入”分别估算，不沿用代码块22.673秒或旧3～6小时外推。历史文件数为 `2 × ΣD_d`，不把七数据集视为同起点。全量字节、日期数、SQL 次数、网络耗时、磁盘峰值和 spill 尚未测量，P0/P3 plan 没有填写完整并通过P3代表样本验收前禁止全量 apply。

## 11. 参数与配置审计

新参数尚未实现。来源、作用范围与消费者集中如下；LLD已展开具体值/消费者/测试，不允许在脚本、页面、sensor 各自写一套值。

| 参数组 | 拟定值 / 来源与持久化位置 | 消费者与生效方式 |
| --- | --- | --- |
| 七表/接口/字段/身份/单位 | 本文及既有源文档；DG schema 与 `run_contracts/moneyflow.py` 的稳定合同 | 请求、bootstrap、writer、check、catalog；代码发布/reload 生效 |
| page/row/request/elapsed/retry | §10及LLD收尾值；同一稳定合同 | Raw source/writer；必须测试三类型和两轮累计预算 |
| 分区登记时间、更新tick、回看窗口 | 每天22:00登记当天partition已由管理员确定；更新tick600秒、回看10日为收尾设计值 | 七数据集各自分区/更新sensor；上海时区，默认STOPPED |
| 本族执行池 | 拟定 `moneyflow_tushare_writer`、容量1；asset合同和正式 instance 已有并发配置机制 | 七 Raw jobs；启用前审核实际配置，不改其他池 |
| Lake/staging 根 | 复用现有 `paths.py`，不新增 env | 路径、writer、bootstrap；挂载/同文件系统/冲突测试 |
| DuckDB 设置 | 既有设置对象传局部512MB/1线程/0spill，资金流合同集中定义，不修改全局默认 | 七writer与bootstrap；staging子目录、RSS768MiB/空间/时间拒绝，测试超限与目录隔离 |
| Tushare 凭据 | 复用当前 `TushareResource` 的 token 来源，不新增 token/env | 日更与来源验证；只报告是否可用，不输出值 |
| Prod 凭据与入口 | 复用 `scripts/psql-remote.sh` 与 `.env.web.local`；不得带入新配置或报告 | 人工只读 audit/bootstrap，schema/table/field白名单测试 |
| bootstrap 执行输入 | 明确dataset、日期范围/集合、operation ID、冻结plan和批次上限；不接受代码边界；存 plan/checkpoint | 仅人工 CLI；不得把连接串、任意 SQL或覆盖开关当自由输入 |

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

P0已核清历史差异、每日完成与异常设计、截止接续和资源边界；仍需P3/P4/P5正式验收日期读取与直接生成候选的吞吐、唯一writer/维护窗口与正式事件量。七数据集独立身份、每天22:00登记当天partition、配额充足已确认，不再列为待决问题。运行证据不能由CodeGraph或文档检查代替。

## 13. 分阶段计划与验收

| 阶段 | 交付内容与退出条件 | 执行边界 |
| --- | --- | --- |
| P0 来源与合同核验 | 七接口规定参数/字段/分页实测；Prod投影、精度、索引、缺日、身份与预算；完成逐数据集7A/LLD、配置审计及Go/No-Go | 只读来源动作按规则；不写正式Lake/事件，不因缺依赖安装 |
| P1 小规模数据集能力 | 先大盘、THS行业/概念，再DC板块；每个数据集独立Raw/Silver、check、隔离fixture验收 | 一轮一个明确数据集/切片；不顺手七数据集一起改 |
| P2 三个个股能力 | 按相同合同逐个实施普通/DC/THS个股，补股票范围、全字段精度、分页压力测试 | 共享能力先做语义审计；不改Prod入口 |
| P3 历史工具与文件验收 | 按§24迁移日期plan/读取/每日候选/checkpoint；取消代码分块及CSV/spool；新路线故障/幂等隔离测试和性能验收；获批单日期样本后分批正式bootstrap及全范围对账 | 正式写湖单独批准，冻结精确命令、日期、读写范围和冲突处理 |
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

当前状态（2026-10-07）：P0来源核验、P1四个小数据集和P2三个个股的候选能力/隔离验收已完成。THS/P2收尾和旧历史规划已提交402c8452，旧CSV导出已提交ada58b50。管理员随后取消代码块与spool路线，本次修订日期方案及LLD；当前步骤见§24。新路线代码迁移、日期读取/内存接收与恢复/性能验收尚未完成。P3正式历史、P4编排/事件、P5新日更未执行；七数据集整体接入未完成。下列P0/P1首轮记录和§15～23均保留各阶段当时事实，不覆盖本段当前状态。

本版完成：七数据集/来源范围、审计基线、字段投影、原单位与身份、两层拓扑、路径/命名、来源切换边界、历史导出与恢复、日更闭合要求、拟定性能/配置预算、实现影响面和验收阶段。

P0 第一轮已完成：七接口规定参数和字段样本、2,000行真实分页及两轮比较、Prod真实列精度、冻结范围逐日计数/业务键唯一性、缺口探测、同日18,320行业务字段对账、100,000行导出/临时转换实验。结果见[ P0 核验与实施合同](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-p0-contract-audit-v1.md)。

历史P0收尾记录：源端可补差异逐键/逐字段核清（14111缺键、212已有值不同）；低覆盖日忠实保留；日更60秒两轮稳定、空/错误/数量异常、10日修订、截止接续及逐数据集7A已落档。当时旧路线分批计划为347个导出unit、694个来源读取事务（当前已由423日期批次/846次读取替代）；15,608个正式文件，局部512MB/0spill、32GiB新增空间预算及12小时累计拒绝线。详见[实施细则与P0收尾](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-low-level-design-v1.md)。P1首个moneyflow_mkt_dc候选切片已按管理员指令开展，实测见实施细则§8。其余P1数据集、P2、P3代表样本与正式提升、P4事件集成、P5真实日更验收仍未完成。

技术方案基线提交只含本文及主索引链接；P0后续新增核验文档和报告，并回填本文与索引。不修改生产API/CLI、DatasetDefinition、资源配置、DG definitions、数据库或正式Lake。方案采用现行路径与单向依赖，不调整依赖矩阵。实施细则与来源差异已落档；全量执行成本须在P3样本验证，历史缺键补录及212个已有值修订按P3精确范围另行决定，默认不覆盖Prod基线。配额不再列为风险或阻断项。


## 15. P0 收尾实施口径（2026-10-06）

[实施细则](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-low-level-design-v1.md)补全本文原拟定细节；与本文联合构成P1设计依据。日更每轮20000行、64次/300秒共享预算、完整轮间隔60秒；非空/大盘1行/未来DC三类非空，两轮不同保留候选不提升；异常下降20%人工复核，最多6次自动attempt。既有资源超时30秒，不新建全局限流服务。仅按合同完整和观测稳定放行，不伪称源站无遗漏。

历史C_d均2026-09-30，10-08起按expected日期完整差集接续。已知6个可取整日缺口10968行及DC部分日3143缺键仅形成待批准补录清单；DC212个已有值差异保留Prod、不自动用最新源覆盖。5个源不可取缺口和早期真实少行数据按已确认原则保留。

局部DuckDB512MB/1线程/0spill配置集中于资金流运行合同并经现有连接设置对象传递，staging子目录为本次temp，作用于本轮writer/bootstrap，不修改共享默认。参数名、值、来源、消费者、生效方式、可见性、测试落点详见实施细则§4/5。正式RSS上限768MiB、磁盘新增预算32GiB/启动空闲64GiB、累计12小时，超限停止，不自动扩配置。更精确全量时间/提升/事件吞吐和恢复验证属于P3；不能用P0样本冒充正式验收。

## 15. P1首个切片进度（2026-10-06）

本轮只实现moneyflow_mkt_dc的15字段合同、共享预算两轮采集、Raw/Silver候选转换及物理对账。两轮至少间隔60秒，空结果或变化不能成为成功候选，金额和NULL忠实保留。代码、正反测试、CodeGraph影响面和验收结果见实施细则§8。

本轮没有新增正式asset/check定义、catalog项、job、sensor、partition或事件；P4才集成这些对象。没有正式Lake写入或Prod写入；历史bootstrap与原子提升/恢复属于P3。当前只完成P1第一个候选能力切片，不能据此把七数据集或整个P1标为完成。其后按管理员“提交吧，然后继续推进”实施moneyflow_ind_ths，进度见§16；继续沿用一个数据集一轮的独立验收。

## 16. P1行业切片进度（2026-10-06）

moneyflow_ind_ths已实现12字段合同、逐页来源持久化、严格SQL精度/整数和身份校验、两轮稳定采集、Raw/Silver候选转换与物理对账。两轮按完整业务集合比较，返回顺序改变不算变化；金额单位亿元及源值忠实保留，不用个股计算替代行业来源。共用候选能力已抽取并同步迁移大盘调用方。

隔离测试95项通过，包含真实90行公开样本读回和两轮各20000行边界；现有治理与静态门禁通过。最大代表样本进程峰值621.12MiB，未突破768MiB拒绝线；60秒等待使用虚拟时钟，未进行真实新日更。硬口径、配置消费者、CodeGraph影响范围、性能边界及实测限制见实施细则§9。

P1行业代码及隔离验收记录已提交141edd3a；整个P1仍未完成。当时下一轮为moneyflow_cnt_ths，当前进度见§17。P3/P4/P5正式提升、事件编排与新日更验收均未执行。

## 17. P1概念资金流进度（2026-10-07）

按管理员指令完成moneyflow_cnt_ths候选能力：独立12字段、Raw/Silver类型、来源/目录/receipt身份，显式分页、两轮完整集合稳定校验与物理对账。金额亿元与源净额不重算，Silver只改日期。行业处理实现整体迁移为moneyflow_ths_board共用模块，所有调用必须指定独立dataset，全部旧行业消费者同步迁移且旧实现删除；共用代码不改变七个独立数据集的口径。

源端20260930公开387行，默认与显式字段一致；归一化/Raw/Silver均387，reject0、业务差异0。概念64项及行业/大盘/策略回归共159项通过，治理12项及474子测试、静态合同113项通过。逐字段JSON重复提取曾触发内存拒绝线，改为多路径批量提取并释放页表；20000行上限连续3个新进程通过，峰值309–343MiB，无预算放宽。设计、配置消费者、CodeGraph影响面、测试及性能证据见[实施细则§10](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-low-level-design-v1.md)。

本轮候选能力已提交c9fcf389；未写正式Lake、Prod或DG状态。当时整个P1尚未完成，下一轮moneyflow_ind_dc，最新进度见§18；历史bootstrap/原子提升与恢复、正式编排/事件、新交易日日更实跑仍留在P3/P4/P5。

## 18. P1 DC板块资金流进度（2026-10-07）

按管理员指令完成moneyflow_ind_dc候选能力，独立18字段、trade_date/content_type/name主键、可空ts_code和源单位元。行业/概念/地域三类显式分页，每轮三类都非空，合计20000行，跨分类/轮共享64次/300秒预算。Raw先持久化来源页，两轮完整集合稳定后才能ready；Silver只改日期，分类物理覆盖、逐字段一致与来源hash/实际scope行数再次对账。

原THS处理模块整体迁移为moneyflow_board共用实现，所有调用要求固定dataset；THS维持date/code键与单scope，DC采用三字段键与三scope。消费者、测试和保护runner同步迁移，旧引用清零；数据集身份、字段、路径和receipt仍分别保存，不改变七个独立数据集口径或正式入口。

源端20260930实测1031行，默认与三类显式字段结果一致；归一化/Raw/Silver均1031，reject0、业务字段差异0。DC新增66项，全部候选/策略225项测试通过，治理12项及474子测试、合同静态113项通过。20000行最坏26请求和最多28候选文件两个边界通过，峰值327/302MiB，未提高预算。硬口径、CodeGraph影响面、配置消费者及来源/性能证据见[实施细则§11](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-low-level-design-v1.md)。

DC修改与P1收尾记录已提交5dc15c94。P1四个小数据集候选能力与独立隔离验收已齐，阶段退出对账见实施细则§12。按管理员本次指令进入P2，先普通moneyflow，再moneyflow_dc/moneyflow_ths，每轮一个数据集。未写正式Lake、Prod或DG状态；P3/P4/P5历史文件、正式编排/事件和真实新交易日日更仍未执行。

## 19. P2普通个股资金流进度（2026-10-07）

普通moneyflow候选能力完成：单日全市场分页、独立20字段和date/code主键，金额万元/量手，所有数值NULL与源净值保留，Silver只转换日期。新增BIGINT严格精度和溢出验证；共用5个板块候选模块整体迁移为moneyflow_daily，固定dataset合同仍独立，现有消费者全部同步迁移，无旧入口别名。大盘模块、共享资源、Prod入口及主体依赖方向不变。实现约束、配置来源与CodeGraph影响面在实施细则§13记录。

MCP真实20260930为5572行，含348行.BJ，Raw/Silver各5572行、reject=0、全字段差异=0。默认20字段与显式查询一致，额外trade_count存在但继续排除在批准投影之外。真实数值循环的20000行压力样本22请求/20页文件，峰值419.7MiB；真实日样本峰值201.0MiB。性能不含真实网络及60秒等待，不能视为正式日更验收。

普通个股127项与P1/请求策略225项合计352项通过；治理12项+474子测试、静态合同113项、Ruff通过。[本轮结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p2_moneyflow_evidence_20261007.json)留档。P2普通moneyflow已提交973d580d；当时下一轮moneyflow_dc，最新进度见§20。P2尚未整体收尾，P3/P4/P5仍未执行。

## 20. P2 DC个股资金流进度（2026-10-07）

moneyflow_dc候选能力完成，独立15字段与trade_date/ts_code主键，name可空且不入键，金额万元/最新价元/比例%原值保留。复用moneyflow_daily分页/两轮稳定/严格数值校验/逐页持久化及物理检查，仅新增DC个股固定schema与候选白名单，不改通用算法、共享资源、Prod入口或依赖矩阵。原“尚未接入DC个股”的未知dataset负例同步迁为moneyflow_ths，既有跨dataset拒绝保留。

MCP20260930返回6024行，SZ3154/SH2522/BJ348，独立键均唯一；默认、显式15字段、关键身份/金额字段一致。源/Raw/Silver6024行，reject0，全字段差异0。本地文档6000条与MCP8000条/实际6024条差异已校准备注，仍沿用P0已实测的2000/2000/2000/24分页，两轮8请求。20,000行真实数值压力样本22请求，峰值379.2MiB；真实样本峰值246.2MiB，保持原768MiB/512MB/0spill门禁。

新增DC个股113项与既有352项共465项通过；治理12项+474子测试、静态合同113项、Ruff通过。开发硬口径/配置审计/CodeGraph影响面和实测边界见实施细则§14，[结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p2_moneyflow_dc_evidence_20261007.json)留档。性能不含真实网络和等待，不等于P5新交易日验收。moneyflow_dc已提交79514a11；当时P2剩moneyflow_ths，当前进度见§21。历史bootstrap/正式提升与DG编排仍属于P3/P4/P5。

## 21. P2 THS个股资金流进度（2026-10-07）

moneyflow_ths候选能力完成，独立13字段与trade_date/ts_code主键，name可空、不入键。金额万元/latest元/比例%保留原值，latest不改为close，net_d5_amount保留源5日主力净额，不从日值重算或依赖前四日分区。新增THS固定schema和候选白名单，通用daily算法、集中预算及正式依赖方向不变；未知dataset负例迁为unknown_moneyflow，跨dataset保护仍保留。

本轮MCP20260930显式/默认/关键字段一致，5215行、SZ2899/SH2316，键均唯一；Raw/Silver各5215，reject0，13字段差异0。实际不含BJ，按本接口源事实保留，不用其他来源补证券；构造BJ身份也不误删。20000行真实数值压力样本22请求、峰值330.9MiB，真实样本峰值270.2MiB，保持768MiB/512MB/1线程/0spill。性能不含网络及真实等待，不能当成新日更验收。

新增THS104项，七数据集及策略联合569项通过；受保护治理12项+474子测试、静态合同113项、Ruff通过。完整约束、配置审计、CodeGraph影响面和实测见实施细则§15，[结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p2_moneyflow_ths_evidence_20261007.json)留档。历史状态：当时P2具备收尾条件；THS修改由本次提交归档。最新收尾/P3开发见§22。P3正式写湖、P4 DG事件/编排、P5新日更须按原方案独立验收，尚未执行。

## 22. P2收尾及P3历史规划进度（2026-10-07，历史记录）

管理员要求P2收尾并进入P3。普通/DC/THS个股独立候选、股票范围/全字段精度、分页压力及共享消费者回归四项退出条件均有代码/正反测试/真实样本证据，P2开发与隔离验收收尾（实施细则§16）。不改变七表独立身份或Prod合同/入口。THS、收尾与P3首轮规划修改由本次提交归档。

本节记录402c8452当时的实现，旧读取路线已由§24替代；以下旧数量、测试与后续安排不作为当前执行口径。

本轮P3实现`defs/bootstrap/moneyflow_history_plan.py`：纯计数计划和受限只读COPY SQL builder；普通按(ts_code,trade_date) keyset，其余六表按日期窗，写窗口年内≤20日且≤100000行。七表按固定schema分别规划，截止日显式冻结，缺日/历史低覆盖保留；schema/count/plan hash变化拒绝。普通下一unit实际边界必须从导出CSV/checkpoint获得，计划不编造证券位置，也不作为APPLY批准。SQL每unit四条语句、120秒，排序使用源索引字段；只允许七张raw_tushare表及批准字段，未添加数据库/Lake/instance执行或CLI入口。

P0公开逐日计数全范围规划与原基线一致：21,160,938行、7,804数据集日期、347读unit、423写窗口、15,608预计正式两层文件；两遍读取694事务、加计划统计至多708连接和2790条SQL。新进程计数规划/首unit SQL生成0.057秒、峰值76.3MiB，不含导出/转换/提升，不作为历史执行耗时预测。未重新查询Prod或核验全量来源内容hash。逐表计划摘要见[结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_history_plan_evidence_20261007.json)。

新增66项规划/负向测试，联合既有候选/策略共635项通过；受保护治理12项+474子测试、静态113项、Ruff及文档检查通过。配置审计、硬口径→代码/测试和CodeGraph影响面回填实施细则§17；无依赖矩阵变化。当时拟推进流式CSV导出与checkpoint、分桶/候选；这一后续安排现已取消，当前下一轮按§24迁移日期路线并重新验收恢复/幂等。整个P3未完成，正式样本仍须精确命令/日期/来源/读写范围/冲突处理获批，P4/P5尚未执行。

## 23. P3来源CSV导出、复核与恢复进度（2026-10-07，旧路线记录）

本节记录ada58b50提交的旧CSV路线；其测试证明旧实现行为，不代表新路线验收，当前迁移任务见§24。THS、P2收尾和P3首轮规划已提交402c8452。当时新增moneyflow_history_export/csv/source三个helper：单unit两遍只读COPY、64KiB流写、严格日期/键/精度的列式校验、逐文件持久化、独立exported/verified状态、取消及跨进程恢复。固定现行连接文件和七表投影，不暴露任意SQL/DSN。来源变化则blocked并保留两份CSV；完成文件恢复须重审hash和实际边界，普通下一unit从已验证CSV的last_key继续。partial与异常现场保留。

新增58项通过，含实际进程退出/新进程续跑、rename与checkpoint之间退出、修改边界不能跳行、同键同行数值变动、源子进程组取消、残缺CSV及NULL标记负例；联合plan/候选/策略693项通过。受保护治理12项+474子测试、静态113项、Ruff通过。10万行真实数值压力样本两份CSV各13,427,932字节，处理2.924秒、峰值278.5MiB；源/导出/复核一致、reject0，幂等恢复不新增COPY。样本使用公开fixture适配Prod CSV口径，不是真实Prod导出，耗时不含远端数据库。硬口径、配置审计、性能和CodeGraph影响面回填实施细则§18，[结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_history_export_evidence_20261007.json)留档。

旧来源CSV修改已提交ada58b50，未执行正式导出、写湖或DG状态变更。当时计划的spool步骤现已取消，下一轮按§24迁移到日期批次直接生成候选；全量入口还须统一七表来源刷新、SQL/连接及整体时间/空间预算和唯一writer，随后独立批准正式样本/提升。整个P3未完成，P4/P5未执行。

## 24. 日期直接生成方案与P3后续步骤（2026-10-07，当前执行依据）

管理员已明确取消按代码导出，采用“Prod按日期批次读取 → 直接生成每日Raw/Silver候选 → 独立来源复核与文件校验 → 逐文件提升”。本节及修订后的§6/§10覆盖§22～23的旧代码块、来源CSV持久化和spool安排。七个独立数据集、来源白名单、字段/精度/NULL、真实缺口、22:00日更、正式路径和P4/P5边界均保持原口径。

### 24.1 现状与代码迁移范围

本节是44904bb0冻结的迁移依据。管理员随后要求按新设计调整旧历史代码；当前代码与隔离验收进度见§25。已有日更候选/schema/check能力保留，旧历史入口已经移除；正式执行尚未进入。

| 当前代码 | 下一轮调整 | 验收要求 |
| --- | --- | --- |
| `moneyflow_history_plan.py` | 七表统一日期批次；取消普通moneyflow特殊代码unit与after/through键；采用新计划版本和hash | 423批计数对账；缺日不补造；年界/20日/100000行反例；旧计划/checkpoint拒绝 |
| `moneyflow_history_source.py` | 沿用固定psql入口、字段白名单和进程取消；按日期SQL读取，业务stdout仅入有界内存缓冲 | 显式日期过滤；代码仅同日排序；越界/超行/超字节/取消/完整传输反例；无持久化CSV |
| `moneyflow_history_export.py`、`moneyflow_history_csv.py` | 重整为日期批次接收、候选生成/来源复核/checkpoint职责；清零旧CSV落盘/代码边界消费者，旧csv文件模块移除或迁移为明确内存解析职责，不保留兼容入口 | 初采直接生成每日文件；复核不生成第二份业务文件；退出后以每日候选和来源证明恢复；没有spool |
| 既有候选路径、Raw/Silver schema、文件check和保护runner/tests | 复用真实字段/精度/路径/物理校验；全量迁移历史调用和保护路径 | 不改日更合同；旧历史路线消费者清零；保留既有日更正反回归 |

正式资产/catalog/job/sensor仍归P4，不因历史helper修改提前登记成功事件。旧测试693项通过只证明旧实现；新路线验收另见§25，不继承旧测试结论。

### 24.2 执行顺序与退出条件

| 步骤 | 工作与产物 | 通过后才能进入下一步 |
| --- | --- | --- |
| P3-A 日期计划与准入依据 | 刷新获准来源的索引/逐日计数；核验单日和日期批次查询计划；按固定日期重算plan/请求量/SQL/空间。实测当前环境内存列式接收、NULL和精度；数据/性能验证范围按现行规则确认 | 不改变Prod索引、连接入口或字段；不能证明有界接收/日期读取可接受则停止评估，不回退代码路线 |
| P3-B 迁移历史执行代码 | 按24.1统一日期unit、日期SQL、内存接收、直接生成每日Raw/Silver候选和新checkpoint；删除旧历史路线全部调用 | 没有来源CSV/spool/代码游标，旧计划拒绝；七表独立身份/截止日/行数和分类合同保持 |
| P3-C 候选复核与恢复隔离验收 | 同日期批次独立来源复核；每日期逐字段与Raw对账；Raw/Silver标准化对账；取消、真实进程退出、续跑、重复执行、rename与checkpoint间退出、来源变化和资源拒绝 | 行数/业务字段/reject解释一致；恢复不信任JSON完成标记；失败不提升、不发绿事件；已提升文件不回滚 |
| P3-D 代表性性能验收 | 早期低覆盖日、近期完整日、接近10万行的日期批次；七表分别记录查询/传输/转换/复核/检查/提升开销、峰值RSS和新增字节 | 512MB/0spill、768MiB RSS、32MiB接收、120秒单次与12小时累计预算不放宽；形成新路线总耗时估计 |
| P3-E 精确正式样本 | 列完整命令、dataset/日期/预计行数、目标/staging、冲突/唯一writer/恢复方式，获批后执行最小样本并读回 | 正式Lake写入另行批准；来源=Raw=Silver行数、精度、业务键和文件事实逐项通过 |
| P3-F 分批历史文件收尾 | 冻结刷新后的精确计划及累计SQL/连接/时间/空间上限；按日期批次推进，聚合对账分区/行数/文件，异常停止 | 当前计数参考为7804数据集日期/21160938行/15608文件；仅实际已完成文件算完成，不用全历史逐分区深扫 |
| 后续P4/P5 | 文件验收后按原阶段集成catalog/资产/check/job/sensor和独立事件补录，再验收DG直连Tushare日更 | 文件与事件分开验收；启用和正式操作按阶段获批；不改变22:00登记或七数据集独立身份 |

按接入模板§7A和§18对账：源契约、日期unit、逐字段、候选/提升、预算与恢复分别映射LLD§19的代码/测试/样本；资产登记、分区事件、入口和正式UI验收仍待P4/P5。新路线的内存接收与每日候选已经完成隔离实测（§25），Prod日期查询吞吐仍待真实核验，整个P3不能标为收尾。


## 25. 日期路线代码迁移与隔离验收（2026-10-07，当前进度）

修订文档已提交`44904bb0`，随后按§24与LLD§19迁移旧历史代码。七表统一年内≤20日、≤100000行的明确日期unit；普通moneyflow不再按代码分块。SQL仅按该unit日期集合读取，代码只是同日排序，LIMIT100001用于发现超限。新plan/执行身份为`moneyflow_history_dates_v2`；旧plan、旧代码边界参数及旧history_export操作目录拒绝，原CSV现场不删除也不读取。

移除`moneyflow_history_export.py`和`moneyflow_history_csv.py`，新增`moneyflow_history_receive.py`与`moneyflow_history_candidates.py`。COPY业务字节仅进入≤32MiB内存；DuckDB直接生成每日Raw，再由对应Raw生成Silver。独立来源复核只保存行数、hash、分类及差异证明，不生成第二份业务文件，也不生成spool。完整候选恢复必须读回真实文件并重读来源；重放复核不改写候选。历史DC分类按真实历史检查，不套未来日更三类齐全要求；日更合同保持原样。

基于已留档P0计数重新规划：423日期unit、7804数据集日期、21160938行、预计15608个两层正式文件；普通moneyflow为217批。该结果不是新查Prod。近10万行的20日期隔离样本生成40个候选、Raw/Silver各100000行、reject0、逐字段差异0，CSV与spill为0，恢复候选hash不变；具体耗时/RSS及当前代码hash留在[结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_date_candidates_evidence_20261007.json)。公开六表旧MCP样本逐字段读回通过；大盘使用独立合约构造样本，不声称本轮七表重新查询来源。

新历史隔离测试包含真实进程退出/新进程续跑、接收取消、完整候选后退出、原生DuckDB interrupt、同键同量改值、旧路线拒绝、单日100000行/100001行、日期/类型/NULL/精度和资源负例。既有七表及请求策略回归、受保护治理/静态检查通过；最终测试数量和运行证据见LLD§20。本轮改动仅历史helper、集中历史预算、测试/保护路径及这两份文档，不改Web/API、Prod合同、共享资源或子系统依赖矩阵。

本轮完成日期路线的代码迁移和候选隔离验收，不等于P3整体验收。当前入口仍只是单dataset单unit helper；下一步先实测Prod日期过滤的查询计划/代表批次吞吐，再补全七表共用操作入口的计数/历史分类刷新、累计SQL/连接/12小时/32GiB预算、历史与日更唯一writer和正式提升/冲突恢复。完整分类集合本轮在unit初采proof记录并通过来源与Raw逐字段相等复核；全量运行前的外部分类冻结尚待来源刷新入口，不用当前JSON证明替代。正式样本及逐文件提升仍须精确范围批准，P4资产/事件、P5真实日更没有执行。本轮代码修改尚未提交。


## 26. 日期代码提交及Prod只读性能核验（2026-10-08，当前进度）

§25日期路线代码、测试与记录已提交`6f7c4ea9`，未推送。本轮依据§24及LLD§19～20，通过现行psql入口对七张Prod `goldenshare.raw_tushare`物理表进行只读核验；截止日保持2026-09-30。先读目录/索引/105个批准字段类型及23个不执行查询的EXPLAIN，再测22个不同日期样本，七个最大批次各读两遍，共29次COPY、806567行。另对普通moneyflow最大批次做一次有界EXPLAIN ANALYZE及一次索引大小目录查询；共32个短只读事务。

COPY字节只进有界内存，再用现行严格接收/归一化代码校验；29次行数都与所选P0日期事实一致，reject0。七个最大批次两次来源hash、逐日行数与分类一致；早期THS 2024-12-19仍为2行，DC板块2023-09-12仍为86行且只有行业，不补造其他分类。最大接收15.02MiB，进程峰值402.55MiB，29次接收/校验总耗时95.793秒；未突破32MiB/768MiB/120秒边界，无DuckDB spill、业务CSV或候选文件。每次COPY耗时包括现行连接及传输开销，不是仅数据库执行时间。

| 最大行数代表批次 | 日期数 | 行数 | 接收MiB | 两次COPY秒 |
| --- | --- | --- | --- | --- |
| `moneyflow` | 18 | 99,839 | 15.02 | 12.109 / 14.766 |
| `moneyflow_cnt_ths` | 20 | 7,890 | 0.82 | 0.837 / 1.111 |
| `moneyflow_dc` | 17 | 99,888 | 12.83 | 7.621 / 6.882 |
| `moneyflow_ind_dc` | 20 | 20,620 | 3.70 | 1.869 / 2.067 |
| `moneyflow_ind_ths` | 20 | 1,800 | 0.18 | 0.706 / 0.556 |
| `moneyflow_mkt_dc` | 20 | 20 | 0.00 | 0.430 / 0.428 |
| `moneyflow_ths` | 19 | 99,070 | 11.42 | 6.674 / 6.816 |

六张表已有可用的日期前导索引，代表查询计划和读取通过。普通moneyflow只有`(ts_code, trade_date)`主键：18日期/99839行批次采用并行整表扫描，数据库执行11.469秒，读取399690个8KiB块，即约3.05GiB堆表。若参考计划的217批均采用同样计划、各读两遍，累计约1.29TiB表扫描量、仅数据库执行约83分钟。这是条件估算，缓存可承接部分读取，不能当成真实磁盘IO或全量耗时；也没有超出12小时硬预算。

建议补非唯一`(trade_date, ts_code)`索引后复测，以降低反复扫全表的Prod负载。它属于新提出的Prod结构变更，不包含在本轮只读核验范围，具体SQL、模型/迁移范围及执行验收在LLD§21.4；本轮未改模型、迁移或Prod索引。也可明确接受现状负载，但不能把现有查询当成已经具备高效日期索引。

[本轮结构化证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_date_query_profile_20261008.json)保存批准投影/精确日期/受控SQL、目录和查询计划、每次接收证明/耗时、代码hash及估算依据，不含凭据或业务样本行。本轮CodeGraph explore覆盖plan→SQL→source→receive调用链，直接读代码补齐测试边；八个源码/测试hash仍与691项隔离验收版本一致，本轮没有重新运行该测试套件。无API、合同、子系统边界或依赖矩阵变化。

本轮关闭代表性Prod日期查询与内存接收核验，不关闭P3-A全部来源冻结或P3-D的候选/提升全链性能。新报告和本节尚未提交；正式Lake、DG状态、Prod业务表均未写入。下一步先确定普通moneyflow的索引优化或扫描负载接受方案，再推进七表统一控制入口的来源计数/分类刷新、累计预算与唯一writer；正式样本、逐文件提升以及P4/P5继续按原阶段单独验收。

## 27. 普通moneyflow日期索引及复测完成（2026-10-08，当前进度）

管理员已确认§26建议的补索引方案。本轮只给Prod `raw_tushare.moneyflow`补非唯一`(trade_date, ts_code)`索引，同步模型与接真实head的新Alembic迁移；不改变业务主键/字段、DG独立数据集合同或依赖矩阵。执行前已确认Prod与本地同为20261002_000183、空闲约51GiB、无目标表锁等待/长事务/并发构建，最小回归35项及Ruff通过。

执行合同、CodeGraph/实际消费者审计、15分钟/15秒会话限额、事务外DDL与最后版本提交、无自动删索引/重试以及固定日期复测详见LLD§22。本轮允许实施这一个索引及对应迁移版本，不执行整库升级、安装部署、正式Lake或DG状态写入。实际索引状态、空间/耗时、相同批次扫描量和来源一致性须完成后回填；P3全量控制入口与正式文件/事件仍后置。


实际结果：Prod索引一次建成，受控执行23.370秒，valid/ready/完整定义通过，新索引423.84MiB；对应Alembic版本已独立读回20261008_000184，原主键不变。相同最大批次数据库执行由11.469秒降至0.129秒，三组查询均使用新日期索引；最大批次完整COPY由12.109/14.766秒降至7.638/7.716秒，不将仅数据库时间冒充传输总耗时。6次读取共344216行全部与建前hash/逐日计数相同，reject0、峰值392.55MiB，无CSV、候选、正式Lake或DG状态变更。优化前434次整表扫读的条件估算不再作为当前性能预测。

§26提出的日期索引问题关闭；执行、恢复与副作用边界和[完整证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_date_index_acceptance_20261008.json)见LLD§22。模型、新迁移及测试最小回归35项/Ruff通过，代码与文档待提交，未推送或部署；Prod已有新迁移版本，下一次源码发布必须包含184文件。P3全量仍未关闭：下一步开发七表统一历史控制入口，刷新/冻结计数与历史分类、闭合七表累计预算与唯一writer，再做获准的候选/提升正式样本和完整性能验收。P4/P5继续后置。

## 28. 七表来源冻结与共享候选控制完成（2026-10-08，当前进度）

§27的模型、184迁移、测试、两份来源/索引报告及方案/LLD已提交`6e25d6e0`；未推送或部署。本轮按§24日期路线推进：新增固定来源聚合与七表cohort控制入口，复用原每日候选核心；七表各有plan/checkpoint/Raw/Silver，只有执行预算与writer共享。没有新增数据集定义、CLI、资产或事件，没有改变Prod业务合同或子系统依赖矩阵。

真实Prod经原psql入口冻结七表批准字段类型、逐日行数/键数和DC历史分类。截止日仍2026-09-30，首轮每表读两次：14连接/56 SQL、77.891秒、峰值96.25MiB，两轮逐项一致。再次恢复每表读一次：另7连接/28 SQL、35.978秒、峰值103.02MiB；来源未变，原manifest未重排/重建，持久账本累计21连接/84 SQL。未读取业务金额或证券明细，未写Prod业务表、候选、正式Lake或DG。聚合冻结事实与P0一致：

| 独立数据集 | 源行数 | 源日期数 | 日期批次 |
| --- | --- | --- | --- |
| moneyflow | 14,089,300 | 4,067 | 217 |
| moneyflow_cnt_ths | 192,009 | 495 | 26 |
| moneyflow_dc | 4,278,673 | 739 | 46 |
| moneyflow_ind_dc | 364,012 | 739 | 40 |
| moneyflow_ind_ths | 44,460 | 494 | 26 |
| moneyflow_mkt_dc | 839 | 839 | 44 |
| moneyflow_ths | 2,191,645 | 431 | 24 |
| 合计 | 21,160,938 | 7,804 | 423 |

正常首次冻结加两次业务来源COPY仍为860连接/3440 SQL，新增人工恢复余量14次，上限874连接/3496 SQL；元数据复核和失败请求同样消耗余量，启动前落账，无自动重试。12小时、32GiB、32MiB接收、120秒步骤及唯一writer共用真实Control/Store，换dataset不重置。已有闭合批次恢复只查checkpoint与实际文件hash；当前未闭合批次继续物理检查与独立来源复核。固定来源或分类变化、文件篡改、旧目录、计数不一致均阻断。详细配置审计、代码/测试对账与预算边界见LLD§23。

六表公开fixture及大盘负值/NULL测试样本共18,320行：源/归一化/Raw/Silver逐表一致，reject0、业务差异0，一次生成14个日文件；新进程构建1.285秒、恢复0.019秒，峰值290MiB，恢复只做7个fake元数据请求，无业务COPY，全部候选hash不变。此测量包含控制/转换/候选读回，不含真实网络或数据库，不能外推全历史性能。七表/策略联合727项通过；最后收紧连接/SQL计数一致性和进度显示并补大账本测试后，历史专项160项再次通过。受保护治理12项/474子测试、静态合同113项、Ruff及文档门禁通过，CodeGraph explore/query/sync/status已核验。

[来源冻结、恢复、候选与代码证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_cohort_evidence_20261008.json)保存批准SQL/hash、冻结类型/日期/分类、21次聚合证明、共享预算与样本checkpoint，不含凭据或业务明细。控制实测和候选测试仅在/private/tmp，未使用正式移动盘；临时驱动在冻结报告后移除，SQL/控制证据保留。

当前关闭P3-A的来源事实冻结、P3-B七表共享候选入口及P3-C候选侧隔离恢复；不关闭整个P3或P3-D。下一步开发逐文件checkpoint、校验后同文件系统os.replace的Raw/Silver正式提升，再按原范围做获准的代表性正式样本与全链性能验收；不能只凭candidates_verified发完成事件。完整历史执行、CLI/资产/事件、P4日更与P5验收继续后置。本轮新增源码、测试、报告和两份文档尚未提交。

## 29. 逐文件提升与隔离恢复完成（2026-10-08，当前进度）

§28来源冻结、七表共享候选与证据已提交 `a55645ee`，未推送。按§24日期路线，本轮新增逐文件提升 helper、集中 Raw/Silver 路径和提升 checkpoint；七表仍是独立数据集。完整候选先全范围核验 hash、冲突、目录和同设备，再对当前 unit 做原完整物理对账；Raw/Silver 逐文件 fsync、原子移入、读回 hash 后登记 checkpoint，无复制/转换/spool，无新增来源请求。同内容幂等复用，不同内容停止。取消、真实进程退出或状态写失败保留已提升文件，恢复从实际目标接回，不重导、不回滚。

提升共用原12小时/32GiB账本和 writer。已移入正式位置的字节仍计入同一空间预算，包括 rename 后尚未闭合的 intent；日期完成量只有 Raw/Silver 都完成后才增加。候选 checkpoint/来源证明保持不变，进入提升后原候选入口拒绝再生成。默认 `apply=False` 只做预检；本轮仅在系统临时目录使用 APPLY，不写正式 Lake、Prod 或 DG，不发布事件或启用日更。硬口径、配置/消费者审计与代码/测试对账见 LLD§24。

两组隔离测量：七表18320行/14文件，提升0.154秒、重跑0.022秒、峰值314.23MiB；普通 moneyflow 100000行/20个合成日期加其余六表，合计112748行/52文件，提升0.459秒、重跑0.046秒、峰值466.09MiB。源/归一化/Raw/Silver行数一致、reject0、业务差异0，原候选/正式/重跑每文件 hash一致，候选 checkpoint 字节不变；每组候选28次 fake请求，提升额外来源请求0。六表金额来自公开fixture，大盘使用负值/NULL合成样本；测试日期不是源历史补齐。耗时包含当前批校验/提升，未包含真实网络或正式盘，不能外推全历史 SLA。

新增36项，联合原历史160项与七表/策略569项，共765项通过；保护治理12项/474子测试、静态113项、Ruff、diff/文档门禁通过，CodeGraph explore/impact/sync/status已核验。[提升与恢复证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_history_promotion_evidence_20261008.json)记录实际文件/receipt hash、字节、进度、代码及测试日志 hash。影响仅 bootstrap/内部路径与控制恢复，没有业务 API/CLI、DatasetDefinition、Dagster definition 或依赖矩阵变更。本轮新代码、测试、报告与两份文档尚未提交。

当前关闭逐文件提升开发与提升侧隔离恢复，P3-D本机测量已补齐；正式磁盘样本及P3整体验收仍未完成。现有提升要求完整 cohort，下一步先补有界真实来源样本入口与明确日期/行数/同设备目标/冲突清单、准确命令和恢复方式，完成隔离验证后提交正式写湖批准。不能裁剪已冻结全历史 manifest、伪造证明或用全量运行替代样本。正式样本还要核对维护窗口与日更 writer；P4日更接入、22:00分区登记、CLI/资产/事件和P5真实日更继续后置。
