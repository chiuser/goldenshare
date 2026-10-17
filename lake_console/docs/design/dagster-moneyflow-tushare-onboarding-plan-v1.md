# Dagster 七个 Tushare 资金流向数据集接入技术方案 v1

> 状态：2026-10-13 P3-F及P3历史物理文件阶段已关闭，每层21,160,938行，共15,608文件，历史源缺口保留，实际结果见§33及LLD§28。P4首个数据集moneyflow_mkt_dc的资产/check/job/catalog、sensor、预演及历史事件执行器已完成，见§34～36；两日样本和全量历史登记均已获批执行并读回通过，见§37～38及LLD§32～33；本表839分区/1678物化/最近20日40检查已齐，源历史缺口保留。moneyflow_ind_ths的资产/check/job/catalog切片和隔离验收完成，见§39及LLD§34；三个STOPPED sensor及历史只读预演完成，见§40和LLD§35；可恢复事件执行器和两日/全量冻结清单完成，见§41和LLD§36，正式两日样本读回通过，见§42和LLD§37；全494日正式登记已读回通过，见§43及LLD§38，494分区/988物化/最近20来源日40检查齐全。moneyflow_cnt_ths独立资产/check/job/catalog及完整隔离验收已关闭，见§44及LLD§39.6；三个STOPPED sensor和历史只读预演已通过，见§45及LLD§40，可恢复历史登记执行器及两日/495日冻结清单已完成，见§46及LLD§41，完整当前门禁已通过并收尾，见LLD§41.6，两日正式样本已读回通过，见§47及LLD§42；495日全量历史登记及收尾完成，见§48及LLD§43，495分区/990物化/最近20来源日40检查齐全；moneyflow_ind_dc的独立资产/check/job/catalog及完整隔离验收已关闭，见§49及LLD§44.3，三个STOPPED sensor、历史预演、执行器和两日样本已完成，见§50～52；739日全量登记及本表P4历史接入已关闭，见§53及LLD§48，739分区/1478物化/最近20来源日40检查齐全；moneyflow_dc独立资产/check/job/catalog及完整隔离验收已完成，见§54及LLD§49；三个STOPPED sensor、readiness及739历史日只读预演已通过，见§55及LLD§50；可恢复登记执行器、隔离两日样本和739日冻结清单已通过，见§56及LLD§51；两日正式登记及读回已通过，见§57及LLD§52；739日全量登记及本表P4历史接入已关闭，见§58及LLD§53；739分区/1478物化/最近20来源日40检查齐全；moneyflow_ths独立资产/check/job/catalog及完整隔离验收已完成，见§59及LLD§54；三个STOPPED sensor/readiness和431历史来源日只读预演已通过，见§60及LLD§55；可恢复执行器、隔离两日样本与431日冻结清单已通过，见§61及LLD§56；两日正式登记及读回已通过，见§62及LLD§57；431日全量登记及本表P4历史接入已关闭，见§63及LLD§58；431分区/862物化/最近20来源日40检查齐全；sensor启用及正式job仍待后续，整个P4未关闭，P5真实日更未执行。七表历史按日期批次直接生成每日候选，取消代码keyset导出和spool，当前方案及新P3步骤见§6、§10、§24。P0/P1/P2既有验收保留；§22～23保留旧实现记录，§31为正式两日样本、§32为全量执行前的范围与成本准备记录。 moneyflow独立资产/check/job/catalog及完整隔离验收已通过，见§64及LLD§59；三个STOPPED sensor/readiness与4067历史日只读预演已通过，见§65及LLD§60；本表可恢复历史登记执行器、隔离两日样本和4067日五单元冻结清单已验收，见§66及LLD§61；正式两日登记、读回及零新增重放已通过，见§67.2及LLD§62.5；4067日五单元全量历史登记及收尾已完成，见§68.1及LLD§63.3。
>
> 日期：2026-10-06。目标：将 Prod 已有七个 Tushare 资金流向数据集接入正式 DG；历史从 Prod Raw 初始化，新增由 DG 直接请求 Tushare。
>
> 本文是实施方案，不是生产执行授权。后续 LLD、代码与执行结果必须回填本文；未完成的来源验证和验收不能预填通过。

最新状态（2026-10-17）：七表历史接入及工具已完成，本轮正式接续推进至39/49，Raw40项、Silver39项。THS个股10-14整理任务启动连接失败，无业务执行或Silver文件；按原方案停止后续提交，整体第一步尚未完成。现有服务健康，21自动更新仍关闭。实际进度及待确认的单次恢复方案见§75.13～75.14、LLD§70.21，不进入启用调度/P5。

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

七表14个Raw/Silver资产共用容量1的专属执行池，符合唯一物理writer边界；数据集与运行状态仍各自独立。当前正式容量尚未设置，后续按明确批准的native配置清单执行并读回，见§69和LLD§64.4。管理员已确认配额充足，P0不再审计共享token额度或任务竞争，不以此阻止接入。现行调用超时、失败重试及本族资源上限继续保留，不调整其他任务或新建全局限流服务。所有新sensor默认STOPPED，按后续阶段批准启用。

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

下表保留最初参数设计和消费者边界；请求/文件预算已在P0～P3落地，首个P4接入不新增可调参数，sensor/运行池仍待其专项验收。具体进度见§33～34及LLD§29，不允许在脚本、页面、sensor各自写一套值。

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

职责按域集中，并将资产/check/job/sensor按独立数据集拆分模块。下表是职责边界，实际落地及验收以最新阶段记录为准：

| 位置（相对 `lake_console/orchestrator/src/orchestrator/`） | 职责 |
| --- | --- |
| `defs/run_contracts/moneyflow.py` | 请求/身份/预算/命名合同；不复制 asset catalog |
| 现有 `defs/run_contracts/asset_column_schemas.py`、`defs/paths.py`、`defs/partitions.py` | 七数据集 schema、路径、专属分区 |
| `defs/source_readiness/moneyflow.py` | 时机与来源稳定/覆盖证据职责，不能写湖 |
| `defs/io/moneyflow_raw_writer.py`、`defs/io/moneyflow_silver_writer.py` | 有界源接收、列式候选及合同校验/提升 |
| `defs/assets/<dataset>.py`、`defs/checks/<dataset>.py`；既有`defs/checks/moneyflow.py`保留纯文件合同校验 | 每个数据集独立2资产/2 partitioned blocking checks；首个模块为moneyflow_mkt_dc.py |
| `defs/jobs/<dataset>.py`、`defs/sensors/<dataset>.py` | 独立selection、typed config、分区注册、日更/阻断、紧凑cursor；首个job模块为moneyflow_mkt_dc.py，sensor尚未落地 |
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
| P3 历史工具与文件验收 | 按§24迁移日期plan/读取/每日候选/checkpoint；取消代码分块及CSV/spool；新路线故障/幂等隔离测试和性能验收；获批日期样本后分批正式bootstrap及全范围对账 | 正式写湖单独批准，冻结精确命令、日期、读写范围和冲突处理 |
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

历史状态（2026-10-07）：P0来源核验、P1四个小数据集和P2三个个股的候选能力/隔离验收已完成。THS/P2收尾和旧历史规划已提交402c8452，旧CSV导出已提交ada58b50。管理员随后取消代码块与spool路线，修订日期方案及LLD，见§24。当时新路线代码迁移、日期读取/内存接收与恢复/性能验收以及P3/P4/P5未完成；该记录不作为当前进度。P3已按§33关闭，P4最新进度见§34；下列P0/P1首轮记录和§15～23保留各阶段当时事实。

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

## 30. 显式日期样本入口与正式执行准备完成（2026-10-08，当前进度）

上一轮逐文件提升九文件已独立提交 `e3ccb04c`，未推送。本轮沿原日期方案，在现有冻结/候选/提升helper增加同一显式日期意图，七表仍各自独立；默认不传日期仍保留原全历史行为/SQL。样本是新完整操作，不裁剪全历史manifest。≤20个有序唯一ISO日期，每表合计≤100000行；无效意图不创建操作/请求来源，超范围/类型/键/行数错误在业务COPY前停止。源没有某日只登记缺口、不造数据；本次七表样本中某一表全空则拒绝。实现、配置/消费者审计、逐条代码/测试对账按原接入模板§7A/§18落在LLD§25。

真正Prod只读刷新2024-12-19及2026-09-30：七表均有这两天，行数分别为moneyflow10678、moneyflow_cnt_ths775、moneyflow_dc11814、moneyflow_ind_dc1117、moneyflow_ind_ths180、moneyflow_mkt_dc2、moneyflow_ths5217；总29783行/14数据集日期/14跨年unit/28两层文件。早日DC板块行业86行，近期日三类；按实际冻结口径验收。14个READ ONLY连接/56SQL，两輪一致，4.029秒、峰值87.02MiB，没有读取业务金额/证券明细。候选新增可选已审计来源hash准入，默认None不改既有调用；正式样本指定真实只读hash，源范围/计数/类型/分类变化时停止且不业务导出，续跑省略参数也不能绕过。

与真实冻结相同的类型/数量/分类，在/private/tmp用公开fixture/合成早日值做同链隔离验收：29783行、28文件、reject0/差异0，构建2.239秒、预检0.035秒、提升0.331秒、重跑0.043秒，峰值358.55MiB，文件4,712,754字节；原checkpoint不变、实际目标hash与候选一致，提升额外源请求0。该测量不是真实Prod业务值、正式磁盘或全历史SLA。新入口39项、联合原历史/提升/七表日更/策略804项通过（79.70秒）；原受保护runner治理12项/474子测试和静态113项、Ruff通过。CodeGraph explore/impact/sync/status和直接源码补核验覆盖原来源/plan/audit/promotion消费者，无API/CLI/DatasetDefinition/active Dagster定义或依赖矩阵变化。

两处正式根仅做只读stat/glob：均已挂载、同设备，当时空闲约2.73TiB，28目标无冲突/邻居文件/符号链接，拟用operation与writer.lock不存在；当前日更资产/job/sensor/catalog没有七表writer。此证据不代替执行时的挂载/权限/空间/冲突和维护窗口确认，不自动停启服务。实际SQL/元数据证明、默认SQLhash、隔离文件/checkpointhash、逐表数量、完整28目标、代码及测试日志hash保存在[本轮证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_selected_dates_evidence_20261008.json)。本轮正式Lake/staging、Prod业务及DG状态写入0；报告与代码/测试/原两份设计回填尚未提交。

下一步仅申请上述两天七表正式样本：operation为history-sample-20261008，候选/控制位于正式staging，批准后用真实PsqlSource重新核对已审计hash并构建，默认提升预检通过才逐文件APPLY。准确工作目录、三条完整命令、两根路径/28目标、29783行、正常42连接/168SQL和56/224上限、共享writer/维护窗口、冲突拒绝、原预算续跑及完成读回见LLD§25.3。不能拿隔离候选移入正式区，不能扩大到全历史、启用日更/登记事件或放宽预算。

当前关闭样本入口与只读/隔离执行准备，正式28文件样本待按AGENTS获得精确阶段批准。P3-D正式盘测量/P3-E及整个P3未完成；即使正式样本成功也仍需对账后另行收尾。全历史、P4七表独立资产及22:00分区登记、P5真实日更按原阶段继续后置。

## 31. 获准正式两日样本执行与读回完成（2026-10-09，当前进度）

管理员要求提交并明确批准LLD§25.3清单。先独立提交样本入口/测试/报告及原两份设计七文件为 `b4567b43`，未推送；再执行原三条正式命令，同一operation history-sample-20261008、2024-12-19/2026-09-30两天与原批准hash保持不变。执行前重新核对正式挂载/权限/空间、28个目标与邻居文件、同设备及writer，均通过；没有停止服务或改变配置。正式根为paths.py中的data_lake/data_lake_staging。

真实Prod两轮元数据等于已审计hash，直接构建并验证14个日期unit；每批两轮业务COPY，源/归一化/Raw/Silver逐表逐日与§30数量一致，共29783行，reject0、业务差异0。正常42个READ ONLY连接/168SQL，两轮业务输入59566行；不写Prod业务表，不使用隔离fixture。完整预检后逐文件原子提升28文件到正式Raw/Silver，读回hash并登记完成；14日期/14unit/29783行到100%，实际文件4,753,392字节。同一APPLY命令重跑通过，来源请求仍42，原候选checkpoint及正式hash不变，无新业务文件写入。

完整进程计时：构建21.02秒/峰值248.98MiB，预检0.50秒，提升1.11秒/212.30MiB，幂等重跑0.61秒。计时包含启动/import/输出，不当作纯SQL时间或全历史SLA。原累计账本保留，连接42/56、步骤时间21.026秒、retained_bytes4,857,359，原预算没有触发或放宽。最后对正式28文件复用原历史audit只读核验schema/日期/主键/逐字段标准化、源两轮proof、checkpoint/hash/大小及promotion receipt，14日期/29783行全部通过，无候选Parquet或.partial遗留；没有新增来源查询或正式写入。正式故障未人为注入，取消/真实退出/续跑证据仍来自前轮隔离验收。

源码在提交后没有修改；39项日期入口再次通过（6.86秒）及Ruff通过，既有804项联合/受保护验收的代码及日志hash复核一致。CodeGraph根索引sync/status最新，无API/CLI、DatasetDefinition、配置、active Dagster定义或依赖矩阵变更。仅写已批准正式staging/28个Raw/Silver，没有Gold、Prod写入或DG instance/分区/event/sensor操作。详细逐表数量、命令、权限/writer清单、源SQL/证明、14checkpoint与28文件hash、计时及读回证据见[本轮报告](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_formal_sample_evidence_20261009.json)和LLD§26；保留§30的只读/隔离记录，不将其冒充本轮真实业务证据。

当前P3-E精确正式样本验收关闭，P3-D两日真实磁盘测量补齐；整个P3尚未关闭。下一步汇总真实日期查询/大批次接收、隔离10万行转换和正式提升的成本，形成P3-F全历史精确计划、目标冲突/幂等与累计预算清单供批准。全历史参考21160938行/7804数据集日期/15608文件尚未执行，本次两个日期以后仅允许同hash复用。P4七表独立资产/catalog/job/sensor/事件和P5真实日更继续后置；完成文件不等于DG资产/分区登记完成。

## 32. 全历史范围、成本和 P3-F 执行准备完成（2026-10-09，当前进度）

本轮落实§31的下一步：只读刷新来源范围，核对全部正式目标，汇总已有测量，并形成准确执行清单。没有导出业务明细或写正式Lake/staging、Prod、Dagster。本节覆盖§31的“成本汇总待推进”状态；正式执行仍未发生。

### 32.1 范围已重新核实

通过原`PsqlMoneyflowHistorySource`→`scripts/psql-remote.sh`读取七表截至2026-09-30的字段类型、逐日数量、业务键及DC分类聚合。每表两轮，共14个短READ ONLY连接/56条SQL，69.65秒、峰值95.58MiB；两轮结果一致，也与§28原全历史冻结完全相同。源缺口及历史DC分类口径保留，不补数据。完整来源合同hash仍为`05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618`。

| 独立数据集 | 首个实际日期 | 行数 | 实际日期数 | 日期批次 | 两层文件 | 已有样本文件 | 待新增文件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| moneyflow | 2010-01-04 | 14,089,300 | 4,067 | 217 | 8,134 | 4 | 8,130 |
| moneyflow_cnt_ths | 2024-09-10 | 192,009 | 495 | 26 | 990 | 4 | 986 |
| moneyflow_dc | 2023-09-11 | 4,278,673 | 739 | 46 | 1,478 | 4 | 1,474 |
| moneyflow_ind_dc | 2023-09-12 | 364,012 | 739 | 40 | 1,478 | 4 | 1,474 |
| moneyflow_ind_ths | 2024-09-10 | 44,460 | 494 | 26 | 988 | 4 | 984 |
| moneyflow_mkt_dc | 2023-04-17 | 839 | 839 | 44 | 1,678 | 4 | 1,674 |
| moneyflow_ths | 2024-12-19 | 2,191,645 | 431 | 24 | 862 | 4 | 858 |
| 合计 | — | 21,160,938 | 7,804 | 423 | 15,608 | 28 | 15,580 |

七表末日均为2026-09-30。日期数是各数据集实际有数据的日期之和，不是7,804个不同交易日；不能据此宣称源日历没有缺口。每批≤20个实际日期、≤100000行、不得跨年；七表分别保存plan/checkpoint/Raw/Silver，只有writer和预算共用。完整批次日期/行数/hash与15,608个准确目标见[本轮报告](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_full_history_plan_evidence_20261009.json)。

只读核对这15,608个目标时持有原writer共享读锁：28已有文件与§31正式样本hash/大小/行数一致，未发现其他目标、邻居Parquet、符号链接或冲突。拟用`history-full-20261009`操作目录不存在；正式Lake/staging同设备16777244、挂载和权限正常，当时空闲2,933,067,976,704字节（约2.73TiB）。这只是当时事实；正式执行前须再次核对，原锁不能覆盖不使用该锁的外部writer。

### 32.2 成本估算与拒绝上限

正常全量需14次来源元数据读取＋423批×2次业务读取，共860连接/3440条SQL；业务源行读取共42,321,876，两遍核对后每层保留21,160,938行。已有两天也重新从源生成候选并做对账；只有新候选与原正式文件hash相同时才复用28文件，所以它们的来源读取成本没有扣掉。预计真正新增7,790个数据集日期、21,131,155行及15,580文件。

耗时按§27索引后moneyflow和其余六表真实最大日期批次的两次COPY测量、§29隔离大批次转换及§31真实正式盘预检/提升推算：

| 项目 | 参考耗时 | 依据 |
| --- | --- | --- |
| 七表元数据 | 1.16分钟 | 本轮14请求实际69.65秒 |
| 两轮业务COPY | 76.69分钟 | 每表最大实测批次的两次COPY耗时×该表批次数；moneyflow使用索引后数据 |
| 本地生成及验证候选 | 44.89分钟 | 隔离112748行/52文件/5.521秒，按总行数与文件数分别放大后相加 |
| 两次全局预检 | 9.29分钟 | 正式28文件预检0.50秒，按文件数放大，独立预检及APPLY各一次 |
| 正式提升与当前批次检查 | 10.31分钟 | 正式28文件整个APPLY进程1.11秒，按文件数放大 |
| 最终只读汇总 | 5分钟 | 计划预留，不是已有全量实测 |

参考合计约2.46小时；考虑网络、缓存、SSD fsync和控制文件成本，按3倍敏感性留余量，建议约2.5～7.5小时维护窗口。这是可解释的估算，不是全量SLA或耗时上界。隔离转换包含接收/校验，未再加`receive_validate`时间；按行数与文件数两项相加是保守代理，不能把它当实测。预检阶段总时间包含多个有界步骤，不能解释成允许某个步骤超过120秒；全范围列目录/布局步骤仍受120秒限制，全量候选规模尚未实测。

两层Parquet按隔离批次字节/行数加小文件开销估约3.77GiB；再留一倍数据余量和1GiB控制/失败候选余量，工作空间约8.53GiB。压缩率和内容不同会改变估算。最大真实接收15,753,317字节，隔离最大RSS466.09MiB，仅证明已测批次低于门禁，不保证全量峰值。公式、逐表输入和报告hash见本轮报告`cost_model`。

**不扩大原硬上限**：874来源连接/3496 SQL（正常860外加原14次恢复余量）；每步骤120秒；累计helper计费12小时；执行空间32GiB，首次准入空闲64GiB；内存接收32MiB、64KiB流块；RSS768MiB、DuckDB512MB/单线程/0 spill。失败请求和续跑仍消耗同一预算；超限或来源/文件差异立即停止，不换操作、自动重试、清目录或放宽。12小时是原账本步骤计费，包含退出步骤预扣，不是覆盖进程启动和最终只读审计的严格墙钟超时；估算范围不改变这个实现。

### 32.3 准确执行顺序和验收

工作目录、原三个helper命令、目标及恢复见[LLD§27](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-low-level-design-v1.md:1121)。拟操作为`history-full-20261009`，固定cutoff和上述完整合同hash；不传`selected_dates`走已验收的默认全历史入口。正式staging为`/Volumes/datasource/data_lake_staging/moneyflow/history-full-20261009`，正式目标仅报告列出的七表Raw/Silver，无Gold、DG instance或`DAGSTER_HOME`。

顺序是：执行前只读复核→在同一次构建内刷新并核对来源hash→依次完成423个候选批次→全范围预检→全部通过后逐文件原子提升→只读物理汇总。**当前代码要求全部候选完成后才能开始提升**；批次checkpoint可续跑，不承诺“生成一批立即提升一批”。来源元数据变化在任何业务COPY前停止；已存在样本内容变化在第一次正式文件提升前停止，不能覆盖。无另一次formal freeze，避免重复消耗7次复核连接。

最终验收以原423个checkpoint/两轮来源证明、每个实际正式文件hash及38个“数据集＋年份”/76个两层日期行数汇总闭合：每层21,160,938行、7,804数据集日期、15,608文件；新增15,580、同内容复用28，拒绝/逐字段差异为0。原当前unit的schema/key/逐字段校验保留，收尾不再调用7,804次逐日深扫。复用模式会保留28个同内容候选在staging，不能误判成未完成或自行删除；禁止未计划Parquet或.partial。`files_complete`只说明历史物理文件完成，P4资产/catalog/job/sensor/事件及P5真实日更仍后置。

本轮补查CodeGraph explore及根索引status，直接源码核对混入同名符号的结果；没有新增QTF依赖、配置、API/CLI、DatasetDefinition或active Dagster定义，依赖矩阵不变。当前十个历史相关模块hash与§31验收一致，既有39/804项测试不重复运行冒充新实测。准确命令做AST/签名核验，14源SQL逐项重生成一致，全部unit边界、原冻结hash及28样本指纹已对账。最终聚合SQL已在这28个正式样本只读验证，错误日期/行数/漏文件三个反例被拒绝；它不代表全量已验收。文档与报告校验结果归档本轮报告。

P3-D成本汇总关闭，P3-F准备完成、正式执行待范围批准，整个P3不关闭。本轮未提交、未推送。依据[orchestrator AGENTS正式门禁第3条](/Users/congming/github/goldenshare/lake_console/orchestrator/AGENTS.md:68)“其他正式环境变更，仍须按阶段获得明确批准”，此前批准仅覆盖两日样本；准确全量范围和命令需独立批准后执行。

## 33. P3-F 全历史执行与物理验收完成（2026-10-09，当前进度）

管理员明确回复“继续推进，批准”，执行范围为§32/LLD§27的原四条命令和精确文件清单。本节更新当前状态，保留§32的执行前估算与准备证据。当前分支仍为`dev-interface`，十个历史模块及四条批准命令hash不变；没有修改代码、配置或扩大预算。

### 33.1 实际完成范围

执行前重新核对15,608个目标、28已有样本指纹、挂载/权限/同设备/空间和历史writer；冲突及writer进程匹配均0，空闲2,933,086,965,760字节。沿用原`history-full-20261009`、截止日2026-09-30及完整合同hash`05dacb35cebe7deb9a581329621fc775dd86311e80b8a7810e9b47abb9b2a618`，七表14次元数据读取与批准manifest完全相同。执行使用原共享writer互斥，不停止服务；该锁仍只约束遵守它的writer。

七个独立数据集全部完成423批候选、全范围预检、逐文件原子提升及最终只读物理验收。逐表行数、日期及文件数与§32.1完全相同：源端、归一化、Raw、Silver各为21,160,938行；7,804个数据集日期，共15,608个正式文件，其中15,580个新增、28个同hash复用。每批两轮源业务字段差异0、reject0，无冲突、重试或计划外文件。七表最晚实际日期均为2026-09-30；源历史缺口保留，不计算补齐，不宣称日历无缺口。

423个原checkpoint在提升前后逐一核对hash不变；28个原正式样本hash不变。最终每个正式文件的实际hash/大小、文件名/日期/行数与原候选及promotion receipt一致，38组数据集年度、Raw/Silver合计76组只读汇总通过。Raw按YYYYMMDD、Silver按DATE校验，并关闭Hive分区推断；不重新逐日扫描所有业务字段。全量实际两轮来源证明和已校验候选的hash连续性承担字段一致性证据，不将其解释为跨全部日期的数据库快照。

正式Parquet合计3,724,770,049字节（约3.469GiB）。28个同内容复用候选按原设计留在staging；无其他候选Parquet或.partial遗留。原正式文件没有覆盖、删除或备份，候选及控制证据保留，未引入Kopia。正式目标只写原清单的Raw/Silver；Prod写入、Gold写入及Dagster访问/分区/event/job/sensor操作均0。

### 33.2 实际成本与门禁

来源共860个READ ONLY连接、3,440条SQL，包含14次元数据读取和846次业务COPY；两轮业务输入42,321,876行。实际SQL均由当前白名单builder重生成核对一致，事务以ROLLBACK结束；提升和最终只读验收没有额外源请求。

四条命令的完整进程计时合计4,391.08秒（约73.18分钟），不包含命令之间的人工核对及等待。构建4,240.39秒、预检11.62秒、提升122.21秒、最终只读验收16.86秒；峰值RSS697.16MiB。§32的2.5～7.5小时是执行前保守估算，本次实耗不能当作后续SLA。完整计时及逐阶段内存见LLD§28。

原874连接/3,496 SQL、单步骤120秒、helper累计计费12小时、执行空间32GiB、首次空闲64GiB、RSS768MiB等门禁均未触发或放宽。helper账本实际计费4,356.21秒，执行保留字节3,731,024,757；APPLY整个进程122.21秒包含多个有界步骤，不代表单步骤超限。峰值RSS高于前轮隔离代理466.09MiB，实际仍低于原上限。

### 33.3 收尾与下一阶段

批准清单、来源SQL/证明、423个checkpoint、15,608个实际文件、76组汇总、逐阶段计时及持续进度证据见[本轮执行报告](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p3_full_history_execution_evidence_20261009.json)。本次未人为注入正式故障或重放全量APPLY；取消/退出/续跑/幂等证据仍为此前隔离及两日正式样本验收。39/804项既有测试的代码hash已复核，本轮不重复运行或冒充新的测试结果。

**P3-F及P3历史物理文件阶段关闭。** 本轮回填原方案、LLD及执行报告，无API/CLI、DatasetDefinition、active Dagster定义、配置或依赖矩阵变更。临时审计driver归档源码/hash后清理，仅保留命令、日志、报告与正式staging恢复证据；不清理业务候选或控制文件。修改未提交、未推送。

下一阶段为P4：七表独立资产、catalog、job、sensor及历史事件接入；P5随后验证DG直接请求Tushare和上海时间22:00登记当天分区。文件完成不等于DG资产或分区已登记，本次批准不扩展到P4/P5。

## 34. P4 首个数据集接入与隔离验收（2026-10-09）

管理员随后要求“推进P4”。按逐个数据集迁移规则，先接入moneyflow_mkt_dc，编码前硬口径/配置与性能设计见LLD§29.1～29.2，实际结果见§29.3。P3历史报告和当时验收记录保留，整个P4未关闭。

本轮新增该数据集独立Raw/Silver两个资产、两个带明确partition definition的blocking check、两个只选择本层的job、一个专属动态分区定义及catalog/中文名登记。15字段保真，Raw完整采集两轮稳定来源后逐文件提升，Silver只读同日已绿且实际hash一致的Raw，不请求源。正常两轮各1请求、各1行；64请求/300秒及60秒间隔、DuckDB512MB/1线程/0spill、RSS768MiB沿用原合同，没有新运营参数。两个check名字集中到原moneyflow命名合同；schema/path由既有稳定合同提供，catalog只登记与对账，不成为资产生成器或运行planner。

日更提升保存intent中的旧/新hash、同设备原子替换及实际读回hash；同值复用，非法旧文件、外部变化、symlink及路径/设备/空间错误拒绝。Raw/Silver各自原子，不称两层事务。将原历史私有writer锁实现提取到io/moneyflow_candidates.py后，全部历史与新日更消费者使用同一个moneyflow/writer.lock，没有旧别名或第二把锁。

验收实际结果：

- 资金流与历史候选/cohort/提升/显式日期最小回归230项通过，其中新资产25项；新资产最终25项再次通过。验证同值复用、修订分层发布、intent后取消保留候选并无源请求续跑、替换后退出恢复及并发/外部目标变化拒绝。
- 临时SQLite instance、临时Lake/staging运行原Raw/Silver job，两项check的evaluation及存储partition均为2026-09-30且SUCCEEDED；注入错日/金额差异后原check FAILED且存储partition仍正确。fake source两轮各1行，Raw/Silver各1行，NULL及负金额保真；文件2562/2537字节，两个job约1.00秒，稳定等待使用虚拟时钟，不能作为Tushare网络吞吐。
- 受保护catalog治理12项/480 subtests通过；完整dg check defs通过，使用现有Dagster1.13.18及隔离DAGSTER_HOME，关闭telemetry并禁止依赖同步/下载。Ruff、文档完整性及git diff --check通过，CodeGraph同步后up to date，无主体边界/依赖矩阵变更。
- 全局静态门禁首批7通过/1失败后停止：当前另一项东财改动的assets/dc_board.py与test_dc_board_m3_writers_keep_raw_only_bounded_boundary中execute_bounded_pages字面量断言不一致（测试:567）。后续未执行；未修改东财业务代码、跳过失败或放宽门禁，不能宣称全局验收通过。

精确命令、最终代码/日志hash、来源receipt、请求参数、实际分区/check存储证明及文件hash归档[首个P4接入证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p4_mkt_dc_evidence_20261009.json)。受保护runner仅补四个新资金流模块，以及当前东财定义已import的两个模块的精确只读源码清单，正式资源和网络隔离不变。本轮无实网Tushare/Prod请求、正式Lake/DG访问或写入，未reload、注册分区、补事件、启用sensor、提交或推送。

下一步完成本表默认STOPPED的22:00分区注册及Raw/Silver更新sensor、有界cursor/readiness和历史event dry-run。正式definitions准入、分区/event写入仍按精确清单独立批准并读回，且先闭合全局静态门禁；之后逐个接入其余六表。P5仍负责真实新增日期采集及观察，本轮不提前关闭P4或七数据集整体接入。


## 35. P4 大盘 sensor 与历史事件只读预演完成（2026-10-09）

上一轮修改已在当前dev-interface提交为`4e5f2f47`，未推送。本轮依据§34的下一步和LLD§30，只继续moneyflow_mkt_dc；其他六表未接入自动编排。历史P3报告及首个P4报告保持原样，本节更新当前进度。

### 35.1 已实现及硬口径对账

- 三个sensor默认STOPPED：上海22:00后注册当日partition，最多另补一个最早漏登记日；Raw/Silver更新器每tick最多一个独立job。注册与更新sensor都不请求Tushare，实际采集仍由Raw job执行。
- 日更使用SSE日历最近10日，SQL直接DESC LIMIT 10；自动来源日期从2026-10-01开始，不因Prod历史缺事件而重新请求历史，也不计算补齐已接受的源缺口。22:00前不做重事件查询或文件hash。
- readiness每层一次mat和一次精确check key查询，最多100记录；核对最新mat/check的partition、blocking、通过状态、target identity和实际文件hash。Silver还匹配同日Raw hash，只有自身原绿证据和文件仍有效时才接受上游修订。未真正执行的check不覆盖已通过证据；真实FAILED/check缺失、文件变化或证据截断须人工处理。
- Raw只对明确标记的临时源错误自动重试，每个业务日期/观察日最多六个标准RunKey；持久化运行记录负责幂等与上限，游标丢失不会重置。游标只保留十日的小状态，不包含事件id或完整报告。文件hash前64KiB上限、原共用writer锁和moneyflow_tushare_writer pool保持有限工作量；启用前仍须核对正式池容量1。
- 只读事件预演逐文件匹配原P3 checkpoint/promotion/hash，最近20日完整核对Raw/Silver字段。已有事件仅在文件hash、Silver的Raw hash及check目标均匹配时复用；错误或变化直接拒绝。本轮没有APPLY或正式事件写入入口。

实现文件为`defs/sensors/moneyflow_mkt_dc_sensor.py`、`defs/asset_guards/moneyflow_mkt_dc_readiness.py`、`defs/bootstrap/moneyflow_mkt_dc_event_preview.py`，来源失败元数据落在原assets/source_readiness/run_contracts三个模块。测试覆盖时间门禁、节假日/当日优先、缺分区、真实partitioned job、临时/永久源错误、持久化六次上限与请求重放、错目标check、实际hash改变/过大、历史控制和已有事件复用的正反路径。

### 35.2 验收与正式只读结果

资金流全量回归837项通过；本轮新模块最终23项通过，随后补充事件复用五种样本及unit symlink读取前拒绝后，预演模块最终11项通过。受保护治理12项/480 subtests、完整静态门禁113项通过；此前§34记录的东财失败保留为历史事实，本次当前工作区该门禁已通过，没有跳过。全defs CLI加载、Ruff及文档/差异检查通过；无业务分层或依赖矩阵变化。

正式DG审计复用现行已审计的只读instance适配器：PostgreSQL默认事务只读、should_autocreate_tables=False、telemetry关闭。实际核验本表839日期/839行、44个unit、1678文件，累计hash4,362,800字节，最近20日共40文件完整校验，90个控制文件前后hash一致。metadata共21次查询；约1秒完成，准确耗时见[本轮证据](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p4_mkt_dc_sensor_event_preview_evidence_20261009.json)。独立临时instance样本的两层readiness仅2次mat查询、2次check查询和2次文件hash，约5ms、590字节cursor；该数字是本机小样本，不是网络SLA。

当前正式差集：839个partition待登记，Raw/Silver各839个materialization待登记；最近20日Raw/Silver各20个check待补，共40个check。日期为2026-09-02～2026-09-30的最近20个实际有来源日期，未把交易日缺口补成绿灯。本轮正式写入0，未reload、启用sensor或运行正式job，也未连接Prod/Tushare。

受保护runner仅增加三个资金流模块及当前全defs审计所需的三个DC模块精确只读路径；static gate仅登记三项sensor身份，并许可此文件的RunsFilter partition tag读取，原RunRequest/tag写入限制不变。CodeGraph explore/impact加直接AST确认调用链及exception消费者，sync/status正常；保留所有其他任务修改。

### 35.3 下一步及阶段边界

下一步仅实现本表历史分区/事件登记执行器，并完成隔离环境的中断、取消、续跑、幂等和实际partition/check identity读回验收。再形成839分区/1678物化/40检查的精确正式执行清单，按原方案独立批准后执行和读回。最近20日以外不伪造检查；正式sensor启用、池配置与P5真实新增日期采集仍后置。整个P4尚未关闭，不将本表进度视为七表已全部上线。

## 36. P4 大盘历史事件登记执行器设计（2026-10-09，编码前）

管理员批准继续§35下一步；上一轮sensor和只读预演已提交fe3510e2。本轮仅实现本表的冻结计划、分批登记与读回，完整硬口径/配置审计/性能预算见LLD§31。顺序是登记原实际日期分区、两层已有文件物化、最近20日40个blocking check、原生事件读回；不重写文件、不补源缺口、不启用sensor或进入P5。

预期全量839分区键/1678物化/40检查，工作项2557，分批100日期；原生查询每次≤100条、总≤256读取API，单次APPLY≤600秒、单批≤120秒、工作项≤4096。先在临时SQLite instance验证取消、实际退出、幂等、状态写失败后恢复、错误实例/文件/计划和native partition/check identity，再准备最近两日样本与全量的精确正式命令清单。共享proof/state从既有只读预演提取，保持其返回合同；新入口默认只读，正式写入未执行，只有已有facts可复用，不以checkpoint创建绿灯。计划/进度只写批准的staging，不能成为第二份完成事实源。

### 36.1 执行器与清单已准备完成（2026-10-10）

本轮把“让DG认识已经落湖的历史文件”做成可恢复执行器：新增event_plan冻结精确范围和实际目标存储，events按批登记分区、物化和最近检查，原preview提供共享只读证明。不会再导出Prod或重写Parquet。取消、进程退出、checkpoint写失败后，已写事件保留，重读原生事实后只补剩余项；重复执行不多记。默认只读，不接入自动definitions或新增CLI开关。

执行器34项与原preview/sensor/history promote65项验收通过；受保护治理12项/480 subtests、完整静态门禁113项及defs隔离加载通过。修正原sensor测试的虚拟时间与日志时间不一致，生产调度逻辑不变。实际839日临时SQLite验收完成2557工作项、1718原生事件，229次metadata读取、1749次原子进度保存，约8.6秒，peak RSS约373MiB；该数字只证明本机隔离执行及预算，正式PG写入成本仍由获批样本确认。所有原控制文件/临时Parquet及源请求次数不变。详细原生退出、取消、续跑、幂等与反例见LLD§31.3和[本轮证据](../../reports/moneyflow_p4_mkt_dc_event_registration_evidence_20261010.json)。

正式只读预检仍为839键、1678物化和40检查差集，写入0；90个原控制证明不变。先行[两日冻结清单](../../reports/moneyflow_p4_mkt_dc_event_registration_sample_plan_20261010.json)覆盖2026-09-29、09-30，仅2键/4物化/4检查；[全量冻结清单](../../reports/moneyflow_p4_mkt_dc_event_registration_full_plan_20261010.json)列出全部839来源日期和文件hash。两份plan hash及准确命令见LLD§31.4。

下一步按§35.3独立批准两日正式登记，先读回partition/check target及两层readiness，再独立批准全量；全量会复用样本，剩余837键/1674物化/36检查。此次没有正式事件写入、reload、pool配置、sensor启用或正式job；其他六表的P4接入和P5不提前推进。原P3和之前P4报告保持原样，不修改历史验收事实。无业务分层/依赖矩阵变化。

## 37. P4 大盘历史事件两日正式样本通过（2026-10-10）

管理员要求“提交修改，然后批准推进下一步”，对应上一轮明确提出的两日正式清单。执行器、测试、设计和两份冻结清单已在dev-interface提交为02fa9045，未推送。本轮仅执行2026-09-29、09-30，不将样本批准扩展为全量、启用sensor或其他六表接入。

上海04:07左右，使用原关闭自动建表的本机PG适配器完成登记：2个专属分区键、Raw/Silver各2条物化和2条blocking检查，共10工作项/8条事件。实际APPLY约1.78秒、53次metadata读取API（另计维护状态及后验查询），checkpoint为complete/100%。两个job无active run；只读维护检查扫描106个sensor状态，三个本表sensor没有持久化启用记录，源码默认STOPPED。写入互斥使用原moneyflow writer，未变更sensor状态。

后验只读差集为0；两日两层readiness全部ready，四条check都是SUCCEEDED、blocking且绑定各自实际mat identity。物化storage id为7438584～7438587（仅诊断，不用于计划身份）。原P3的90个控制hash及1678个本表正式文件匹配原冻结证明，没有Parquet改写，也未访问Prod/Tushare、reload、配置pool或提交job。结果和原生身份读回详见[正式样本证据](../../reports/moneyflow_p4_mkt_dc_event_registration_formal_sample_evidence_20261010.json)及LLD§32。

全量原清单hash仍为e699ce04e04ed8e792a95ff72140251945aa282cda0b18ed25972517357ce92d；样本已占10项，全量实际剩余2547项：837分区键、1674物化、36检查。下一步按原§35.3/LLD§31.4独立批准该全量清单，再复用样本补齐剩余；不重新生成历史文件或修改源缺口。正式两日速度不是全量SLA，原600秒/批120秒/256次读取预算仍必须执行，触限保留已提交项后停止续跑。本轮仅回填两份设计文档和新增样本报告，没有代码或依赖边界变更，之前所有报告保留原字节。

## 38. P4 大盘全量历史事件正式登记完成（2026-10-10）

管理员明确批准“提交修改，然后批准按全量清单执行，继续推进”。两日样本验收的两份文档和报告已在当前dev-interface提交为`c1058a05`，未推送。本轮执行原839来源日期全量清单，plan hash仍为`e699ce04e04ed8e792a95ff72140251945aa282cda0b18ed25972517357ce92d`，范围仅moneyflow_mkt_dc历史登记。

上海13:52左右，原本机PG适配器完成新增837分区键、1674物化及36条blocking检查；原两日样本的4个物化storage id保持不变。最终839分区、1678物化、最近20个实际来源日的40检查齐全，2557/2557工作项完成。APPLY实耗30.140秒、229次helper metadata读取，checkpoint为complete/100%，进度单调。未触发或放宽原600秒/单批120秒/256读取预算。维护状态及外部前后验查询另计，229不是底层SQL总数或后续SLA。

执行前及后验核对原90控制证明和1678本表文件，hash均匹配；最近20日以正式SQL完整检查两层字段，随后按每批10日读回两层readiness，40项全部ready。全量后验缺分区/物化/检查均为0；更早日期只有文件证明和物化，不伪造检查，不补源缺口。本轮没有Parquet改写、Prod/Tushare请求、reload、pool修改、sensor启停或job执行。原25份历史报告与冻结清单保持原字节；代码hash与99项既有验收一致，无代码、API/CLI、配置合同或依赖矩阵变更。执行证据及原生身份见[全量正式报告](../../reports/moneyflow_p4_mkt_dc_event_registration_formal_full_evidence_20261010.json)，准确命令及硬口径对账见LLD§33。

### 38.1 下一步条件已只读核对

| 条件 | 2026-10-10上海13:53～13:54实际结果 | 后续动作 |
| --- | --- | --- |
| 本表历史登记 | 839分区/1678物化/40最近检查全部齐，差集0 | 本表历史登记收尾，不重放写入 |
| 正式definitions | orchestrator / __repository__已LOADED，可见本表两个job和三个sensor | 无需为“未发现定义”重新创建或reload；仅证明这些身份已加载，不证明加载进程所有源码hash与工作区相同 |
| 自动化维护状态 | 三个sensor默认及有效状态均STOPPED，无本表active job | 保持停止，独立准入后启用 |
| 专属请求执行池 | moneyflow_tushare_writer没有持久化limit，slot=0，pending=0 | 日更启用前按原合同设置容量1并读回；不修改其他池 |
| 历史与日更边界 | cutoff=2026-09-30，sensor start=2026-10-01；正式SSE日历窗口只有10-08、10-09，两日分区及Raw/Silver文件均缺 | 后续真实日更验收按这两个明确日期接续，不把9月历史重新请求；源可用性尚未实测 |
| 其他六表P4 | 尚未完成独立资产/job/sensor和原生历史事件接入 | 按原卡片逐表推进，下一开发切片moneyflow_ind_ths；不批量启用七表 |

**本表历史登记阶段关闭，整个P4保持开放，P5尚未进入。** 下一步沿原P4逐表接入，不把本次全量历史批准扩展为池配置、sensor启用或实际Tushare日更。上述准入审计只读，不执行sensor dry-run、不保存cursor或发run；接续日期仅证明当前正式日历窗口，不证明源站已有数据或未来日历完整。

## 39. P4 下一开发切片：同花顺行业资金流（2026-10-10，编码前）

管理员要求提交并继续§38.1的下一开发切片；全量大盘登记文档/报告已提交059ec20b。本轮只实现moneyflow_ind_ths独立Raw/Silver、专属分区、两检查、两job及catalog，依据LLD§6实施卡和§34硬口径/配置/性能设计。复用12字段候选writer与正式SQL，不将90行业行误当成大盘单行，不合并七源或裁剪行业/股票池。

为避免重复维护取消/退出/续跑逻辑，将大盘现有逐文件发布协议抽取为共用纯IO能力，两表各自保留来源与校验，保持大盘入口、revision及行为不变，迁移全部内部消费者和测试注入点，不保留旧副本。隔离验收包括真实归档90行fixture、明确partitioned job/check原生读回、异常不发布、幂等/取消/退出恢复，并回归大盘、行业候选及受保护catalog/static门禁。

本轮正式Lake/PG/分区/event/job/sensor/pool操作0，不重建已完成的行业988历史文件。新增sensor、历史登记与正式日更是后续步骤，整个P4和P5仍按原阶段边界推进。MCP额外源复核未取得结果及在线文档连接失败均记为本轮证据限制；原P0/P1真实样本和现行合同可追溯，未改请求字段/参数，不声称新的源端实测通过。

### 39.1 行业资产切片完成，后续边界不变

两个独立资产、两个blocking检查、两个job、专属动态分区与中文catalog已落地。Silver只消费同日已绿Raw并核对实际文件hash，12字段保真且仅改日期类型；共用逐文件发布协议已抽取，大盘原行为回归通过，没有双轨实现或新增配置。

行业/大盘定义与发布55项、候选80项、受保护目录治理12项/486 subtests及静态113项全部通过，完整definitions隔离加载成功。真实归档90行样本通过两个实际隔离job：两轮源各90、Raw/Silver各90、reject 0；两检查同日SUCCEEDED且绑定正确物化。Raw8110B/Silver8086B，两个job531.434毫秒是fake请求与虚拟时钟的本机成本，不代表真实网络日更耗时。Ruff、文档完整性和差异检查证据见[本轮报告](../../reports/moneyflow_p4_ind_ths_evidence_20261010.json)与LLD§34.3。

本轮未完成新的实时Tushare复核，使用此前已验证并归档的真实样本，字段/参数合同未改；P5仍须新日期真实验收。所有正式Lake/Prod/PG/event/分区/job/sensor/pool写入、reload为0，原历史证明保留。本开发切片完成，整个P4尚未关闭；下一切片只接入本表注册/更新sensor和历史登记预演，正式登记或启用按后续明确清单审批，不转入下一数据集或P5。

## 40. P4 行业调度与历史登记预演（2026-10-10，编码前）

行业资产切片提交5033dc1f。本轮按§39.1和LLD§35接入三个独立STOPPED sensor：专属注册器、Raw更新、Silver更新；沿用上海22:00、SSE、最近10日、一次一run、六次有限attempt和小cursor。审计发现通用collector未传递原方案要求的临时错误retryable，按原分类补齐，不改字段/请求或校验通过条件。

抽取大盘既有selection、batch readiness与history proof/state作为共用实现，全部原消费者/测试同步迁移；两表各自固定身份，catalog不参与运行。历史预演只核行业494来源日期/988文件/最近20日40检查以及现行PG差集，约13 native读取，不逐日查event、不重建文件、不写分区/event，不启用sensor或改变pool。sensor分类同步治理与拓扑文档。正反测试、10日热路径实测、全历史纯只读预演与大盘回归完成后回填结果；下一切片为本表可恢复事件执行器，正式APPLY仍须精确清单批准。

### 40.1 行业调度与只读预演完成

三个专属sensor默认STOPPED：上海22:00注册、Raw更新、Silver更新。两层更新按原最近10日/一次一run/六次attempt约束；通用采集器补齐临时源错误分类，身份/字段/精度/预算错误仍阻断。共享readiness、selection和历史proof/state保持一份实现，原大盘入口及执行器revision不变，消费者和测试注入点一并迁移。

行业调度23项、六表采集及两表定义582项、大盘调度/预演/执行器及行业预演76项通过。最终受保护静态113项、catalog12项/486 subtests及完整隔离definitions通过。10日行业Silver tick的隔离样本实测23.420毫秒、7次native读取、20文件161960B、595B cursor；用归档真实90行数据和合成日期，不作为正式日更或未来源端证明。

正式纯只读预览确认494日期/44460行/988文件8004292B匹配原证明、54控制不变，最近20来源日两层40文件标准化对账通过。原生差集为494分区、988物化、40检查，合计1522工作项/1028事件；13次native读取、约0.83秒。没有生成历史文件或写入正式事件，也没有Prod/Tushare请求、reload、pool或sensor/job操作。原27份报告/清单保留原字节。格式化误扫已逐文件核对撤回，最终门禁重新通过；详细证据和硬口径对账见[本轮报告](../../reports/moneyflow_p4_ind_ths_automation_evidence_20261010.json)与LLD§35.3。

本开发切片完成，整个P4仍开放、P5未进入。下一步开发行业可恢复事件执行器，形成两日样本及全494日的冻结清单；实际登记仍分别按清单批准，本轮不提前执行。

## 41. P4 行业可恢复事件执行器（2026-10-10，编码前）

行业sensor/只读预演提交bf6fa7bf。本轮按§40.1及LLD§36开发行业可恢复事件登记，抽取大盘现有plan/执行协议为一份共享实现，两表显式绑定各自身份；大盘原公开入口、revision和正式清单哈希保持不变。行业逐日row_count取P3冻结date_counts，不能复用大盘固定1行或假定全历史固定90；物化与check均记录正确数量。仅最近20来源日复用正式SQL补绿check，不补源缺口或重建Parquet。

继承登记→物化→check→原生读回、writer互斥、逐事件checkpoint/fsync、取消/退出/幂等恢复和原600秒/每批120秒/256读取/4096项预算；隔离验证不同日89/90行及完整494日期/988物化/40检查规模，回归大盘和受保护门禁，之后只读冻结两日/全量正式清单。没有正式APPLY、reload、pool或sensor/job操作；本轮验收后再按精确清单批准样本和全量，P4仍开放、P5未进入。

### 41.1 执行器与精确清单完成（2026-10-11收尾）

行业可恢复登记已实现：两表共用一份plan/执行协议，固定适配器隔离身份；行业逐日行数以P3证明为准，已有物化/check数量冲突时停止，不给坏记录补绿。大盘原公开入口、单行口径、revision及两份正式清单hash均经重构后实际验证保持不变。

行业执行器、大盘回归和两表预演103项通过，包含真实子进程退出、取消—续跑—读回、幂等、状态写失败和原生target/不同日行数的反例。494日隔离容量完成1522工作项/1028事件，141次native读取、1047次原子控制保存、最大日期批100，5.296秒、peak RSS约424.9MiB；该成本来自临时SQLite/归档样本合成日期，不作为正式PG或Tushare承诺。最终受保护静态113项、catalog12项/486 subtests、完整隔离definitions、Ruff、文档及diff检查均通过，CodeGraph影响面分析及开发后sync/status完成。

正式只读已核对原54控制及988行业文件8004292B、494实际来源日/44460行；两job无active run，未发现可复用本表事件或分区。新[两日清单](../../reports/moneyflow_p4_ind_ths_event_registration_sample_plan_20261010.json)为09-29、09-30共2键/4物化/4检查，[全量清单](../../reports/moneyflow_p4_ind_ths_event_registration_full_plan_20261010.json)为494键/988物化/40检查。样本预检7次读取约0.377秒，全量15次约0.409秒；逐日row_count、精确hash与批准后命令见LLD§36.4，完整硬口径对账见§36.1～3及[本轮证据](../../reports/moneyflow_p4_ind_ths_event_registration_evidence_20261010.json)。原28份资金流报告/清单保留原字节。

本轮正式Parquet/PG/分区/event/job/sensor/pool写入、reload及Prod/Tushare请求全部0。没有新增运营开关、API/CLI或主体依赖矩阵变化。下一步先独立批准并执行两日正式样本，核对维护状态、四条原生check target、两层readiness和原证明；之后再独立批准原全量清单，复用样本补齐剩余492键/984物化/36检查。sensor启用及真实日更仍后置；整个P4开放、P5未进入。

## 42. P4 行业历史事件两日正式样本通过（2026-10-11）

管理员要求“提交修改吧。然后推进下一步，执行吧”，对应上轮明确提出的两日正式清单。执行器、测试、两份冻结清单及文档已在dev-interface提交6039fd37，未推送。本轮仅执行moneyflow_ind_ths的2026-09-29、09-30，清单hash仍为72cab9be9af8b53cf47463acce087598dfe31c402161bf9c792149d2bb4a7e3b；不把两日批准扩展为全量、sensor或job。

上海15:05左右，在既有本机PG完成2个专属分区键、Raw/Silver各2条物化及2条blocking检查，共10工作项/8事件。APPLY 1.538秒、53次helper状态读取、60条进度记录，checkpoint complete/100%，完成量单调。前后原生维护读取均未发现本表活动job或sensor持久化启用记录，当前导入的三个sensor定义默认STOPPED；使用独占moneyflow writer。执行器由新进程直接导入已验收提交，实际加载项目源码hash一致，未reload或依赖code location运行job。

后验样本三类差集均0，四项Raw/Silver readiness全部ready。两日每层90行，物化source_row_count及check checked_row_count都为90；四条SUCCEEDED检查绑定本层准确partition和物化storage_id/run_id/timestamp。原494日/988文件及54控制证明保持不变，最近20来源日两层40文件正式SQL对账通过，没有Parquet改写、Prod/Tushare请求、pool/sensor变化或job执行。原31份历史报告与清单保留原字节；本轮只回填两份文档和新增[正式证据](../../reports/moneyflow_p4_ind_ths_event_registration_formal_sample_evidence_20261011.json)，没有代码、源合同、API/CLI或依赖矩阵变化。完整命令、恢复边界及读回见LLD§37。

原全量清单hash仍为7dbc2c4f08774552f6f0fafa8f423338980d53fb262a300ce09506e4a1cbdc1c，实际剩余492分区、984物化、36检查，共1512工作项/1020事件。下一步独立批准[原494日全量清单](../../reports/moneyflow_p4_ind_ths_event_registration_full_plan_20261010.json)，复用样本已写物化身份补齐剩余，并按原600秒/批120秒/256读取等门禁执行；两日速度不是全量SLA。全量尚未执行，P4保持开放、P5未进入，pool/sensor启用及真实日更仍后置。

## 43. P4 行业全量历史事件正式登记完成（2026-10-11）

管理员回复“提交吧。然后继续推进”，对应§42明确的原494日全量清单。样本收尾文档和证据已在dev-interface提交5e705f45，未推送；原执行器源码及全量清单hash 7dbc2c4f08774552f6f0fafa8f423338980d53fb262a300ce09506e4a1cbdc1c保持不变。本轮上海15:19完成新增492分区、984物化及36条blocking检查，共1512工作项/1020事件；原两日样本四条物化storage id复用，没有重写历史文件或补源缺口。

最终494分区、988物化和最近20个实际来源日40检查齐全，三类差集均0，checkpoint complete/1522项/100%，进度单调。每日期的物化/源计数匹配原P3清单，40检查全部SUCCEEDED并绑定准确partition和mat identity，最近20日两层40项readiness均ready。APPLY实耗17.301秒、141次helper状态读取；原600秒/批120秒/256读取和100日期批门禁未触发或放宽，维护/外部前后验和写API内部SQL另计。

原54控制hash及988行业文件8004292B前后一致，最新20来源日复用正式SQL做两层完整标准化对账；更早日期保留物化和物理证明，不伪造check。原32份历史报告/清单保留原字节；本轮只回填两份设计文档和新增[全量正式证据](../../reports/moneyflow_p4_ind_ths_event_registration_formal_full_evidence_20261011.json)，没有代码、源合同、API/CLI或依赖矩阵变化。Prod/Tushare请求、Parquet改写、job/sensor/pool操作和reload均0；准确命令、原生身份及后续准入见LLD§38。

后续准入只读发现正式workspace为LOADED，但现有清单未包含行业两个job和三个sensor；源码及隔离defs已通过，日更前仍需另行批准加载当前代码并核验。共享请求池尚无持久化容量，slot/pending为0，后续按原合同设容量1；本轮未修改。正式SSE日历接续窗口只有10-08、10-09，两日行业partition/Raw/Silver均缺，尚未证明源可用性。

本表历史事件登记阶段关闭，整个P4保持开放、P5未进入。下一开发切片沿原实施卡接入moneyflow_cnt_ths独立资产/check/job/catalog，再逐步接入sensor和事件，不批量启用；正式代码加载、池配置、sensor启用和真实日更另按精确清单推进。

## 44. P4 同花顺概念资产开发切片（2026-10-11）

行业全量登记收尾已提交70ee1cc9。管理员明确继续moneyflow_cnt_ths，本轮按原逐数据集实施卡接入该表独立Raw/Silver、专属分区、两个blocking checks、两个独立job和catalog。12字段、金额亿元、industry_index DECIMAL(24,4)及495日既有历史保持原口径。行业日更helper迁为要求显式dataset的共用helper，同步迁移全部消费者，不复制发布协议或留兼容入口；大盘、Prod合同和主体边界不改变。编码前硬口径、消费者、配置审计与请求/内存/文件/恢复预算见LLD§39。

本轮使用09-30真实归档387行fixture、源替身和隔离instance做partitioned job/check验收；不将它称为新交易日实测。sensor、历史预演/登记、正式加载/池/日更按后续精确阶段推进，P4开放、P5未进入。

本轮独立asset/check/job/catalog与共用日更helper代码已落地。概念及行业定向64项、相关回归211项通过；已归档387行样本源/Raw/Silver一致、reject0，全12字段逐值对账通过，两层原生同分区checks通过；Raw24534B、Silver24510B，两job隔离耗时532.680ms，虚拟稳定等待不代表网络SLA。改动文件Ruff及全库致命检查通过。

首次完整验收尚未关闭：当时未提交的股票周线代码新增模块未进入受保护runner清单，catalog导入/静态读取阻断；完整隔离defs因其stock_weekly_adj_run.py缺psutil失败。该历史结果保留在LLD§39.3和[本轮证据](../../reports/moneyflow_p4_cnt_ths_evidence_20261011.json)。没有正式资源操作，本表sensor/历史登记后置，P4开放、P5未进入。

管理员批准下一计划第1步后，于2026-10-11上海22:48在HEAD b49d9cdc复验；概念资产b2793920的13个代码/测试hash不变，周线已提交。完整隔离dg check defs退出0，上次缺依赖阻塞已消失；受保护catalog第一批在导入stock_weekly_adj_run时collection失败，受保护static gates第一批读取prod_db/stock_weekly_adj_delivery.py时PermissionError，均因周线新增模块未同步进入runner的consumer源清单。两项没有全库通过，不能关闭概念资产切片。精确结果、隔离边界和下一步见LLD§39.4及[第1步复验证据](../../reports/moneyflow_p4_cnt_ths_acceptance_evidence_20261011.json)。

第1步三项复验已执行，但收尾条件未满足。需周线开发核对新增导入闭包、同步受保护精确清单，再重跑catalog与static gates；完整defs仅在源码再变时重跑。周线已提交，当前阻塞是测试清单未同步，已不同于首次的未提交工作区冲突。本轮批准原样复验，未包含周线测试能力清单迁移；按完整门禁验收要求停止下一切片，不修改其他模块、放宽测试权限、安装依赖或执行正式操作。只回填两份原文档与新证据，保留原34份资金流报告及旧日志。sensor、495日历史预演和登记仍后置，P4开放、P5未进入。

随后管理员要求“提交，然后继续推进”，上述复验记录已提交1a980036。本轮按LLD§39.5审计周线b49d9cdc新增6模块及49文件传递导入闭包，仅给受保护runner补这6个精确源码路径；policy、其他scope、测试断言、预算和正式权限不变。catalog完整12项及492个subtests、static gates完整113项/15批、完整隔离dg check defs全部通过；17批原生自检与各7个负例通过，拒绝哨兵不变、正式连接0。runner Ruff、全库致命检查、文档/diff/链接、CodeGraph sync/status通过。

其他周线任务期间的两份业务文件改动保留；全部suite源hash与当前匹配，最终defs记录前后hash一致。原35份资金流报告与清单保留，资金流业务代码未变，源字段、配置、正式路径和主体依赖矩阵不变。具体身份、实际批次和日志hash见LLD§39.6及[第1步收尾证据](../../reports/moneyflow_p4_cnt_ths_asset_closeout_evidence_20261011.json)。moneyflow_cnt_ths资产/check/job/catalog切片完整验收关闭；整个P4开放、P5未进入。下一独立切片是概念三个STOPPED sensor及495日历史有界只读预演，正式登记/加载/pool/日更仍后置；本轮没有进入这些操作。

## 45. P4 同花顺概念 sensor 与历史只读预演（2026-10-11，执行前）

管理员批准提交并继续，§44资产收尾已提交96475a31。本轮沿原P4逐表切片，仅实现概念专属三个STOPPED sensor、readiness适配器、固定合同及历史只读preview。复用已验收行业通用选择/注册、readiness、历史proof/state，概念cursor/check/job/分区/revision保持独立；上海22:00、600秒、10日、6次、100记录和20最近来源日等预算不变。原大盘/行业全部合同与入口回归，未知数据集拒绝，受保护精确源码清单和静态sensor身份同步。

495实际来源日/192009行/990文件沿用冻结P3证明，不补源缺口；正式只读预演预计13 native读取，实际差集、字节、控制及最近20日SQL结果必须读回，不预填通过。隔离10日热路径用归档387行样本与合成未来日期，记录API/SQL/hash/cursor/耗时。硬口径、代码消费者、固定身份配置审计和性能门禁见LLD§40。没有概念APPLY开发或正式登记、sensor启用、pool/reload及新增来源请求，P4开放、P5未进入。

本切片已实现并验收：三个独立STOPPED sensor、固定概念automation/readiness及纯只读preview完成；上海22:00、600秒、最近10日、六次有限attempt、专属cursor/check/job身份保持原口径。概念30项sensor及15项preview通过；首次测试误用了行业check名称的3项失败已纠正测试归属并重跑，保留旧日志。两表sensor/preview/历史plan/APPLY与sensor-tags147项回归通过，受保护catalog12项/492 subtests和static113项完整15批、完整隔离defs、Ruff、文档/diff/链接及CodeGraph门禁通过。

正式只读读回495日/192009行/990文件24402584B及54控制全部匹配；最近20来源日两层40文件/20组标准化SQL对账通过。差集为495分区、990物化、40检查，无本表可复用事件；13 native读取、0.8409秒、正式0写入。10日归档387行隔离热路径22.914ms，1日历SQL、7 native读取、20hash文件490440B、cursor595B、tick源请求0；不外推源网络SLA。原36份资金流报告/清单原样保留，最新结果见LLD§40.3及[概念自动化证据](../../reports/moneyflow_p4_cnt_ths_automation_evidence_20261011.json)。

本切片关闭，P4整体开放、P5未进入。没有正式服务reload、pool配置、sensor启用、分区/event登记、正式job或新源请求，主体依赖矩阵不变；下一独立开发切片为概念可恢复历史事件执行器及两日/495日冻结清单，正式样本和全量APPLY仍各按精确清单准入。


## 46. P4 概念历史登记执行器与两日、全量清单（2026-10-11，开发前）

管理员要求提交并推进本切片，§45自动化已提交76d61613。按LLD§41实现固定concept event-plan/events适配器，并将共享执行器两处行业行数校验扩展到概念；保持原大盘/行业清单、revision和运行入口。隔离样本覆盖默认只读、两日386/387行、错误来源/事件行数、取消、真实进程退出、checkpoint失败、续跑和幂等；隔离495日容量验证100日批次、最近20日check、实际读取/时间/RSS及控制保存成本。

正式实例仅使用既有只读适配器，验证990物理文件和54冻结控制后生成2026-09-29/30两日清单及全495日清单，归档实际差集、hash、数量和耗时。新清单写仓库reports，禁止默认APPLY及创建正式events目录，不启用sensor、不reload/pool、不请求源或重写历史文件；P4开放，P5未进入。正式样本和全量执行分别后置精确清单审批。


本切片代码与清单完成、整体门禁未关闭：概念固定event-plan/events适配器与共享逐日行数守卫落地，概念46项及旧两表79项通过。495日隔离SQLite完成1525项/1030事件/495分区，APPLY7.8053秒、141次读取、RSS约533MiB、1049次原子保存。首次仅保存次数预估多1导致失败，纠正测试模型后重跑全部46项，不改业务行为。周线另一个任务随后改一份DG源码，完整catalog12项/492 subtests、static113项/15批和隔离defs已重新全部通过，刷新时源码hash一致，随后周线又改三份共享DG文件，完整门禁已不对应当前版本；概念5个Python源hash不变。按根AGENTS第29条停止下一阶段，等待周线源码稳定后复验完整catalog/static/defs，不另建分支或worktree绕过。

正式默认只读，无自动DDL；990文件/54控制/192009来源行证明匹配，原市场、行业四份计划重构相等。[两日清单](../../reports/moneyflow_p4_cnt_ths_event_registration_sample_plan_20261011.json)为2026-09-29/30，共774行，2分区+4物化+4检查，plan_hash=728f979259727100dab6bf7598a491f64a7fd8254e3255ddfa85e93de6426d5b。[全495日清单](../../reports/moneyflow_p4_cnt_ths_event_registration_full_plan_20261011.json)为495分区+990物化+40检查，plan_hash=ff4a6fd4ab4dc4f98eb1ee479c9938a6d3076d0d95949455211f51b2c1329c77。两份读回重构通过，正式staging/events库存原样，正式写入0；原37份资金流报告/计划不变。详情见LLD§41.3～4与[执行器证据](../../reports/moneyflow_p4_cnt_ths_event_registration_evidence_20261011.json)。

开发和冻结清单已完成，当前完整门禁待复验，切片未关闭；正式样本和全量未执行，P4开放、P5未进入。下一阶段先稳定工作区并复验完整门禁，再按两日清单独立准入，维护核验后执行并读回check身份/readiness/物理证明，再准入全量。样本后预计全量剩493键/986物化/36检查（1515项/1022事件），保留完整冻结清单并按原生事实续跑。不含reload、pool、sensor启用或日更job；主体边界、正式Lake路径、源参数和配置不变。


2026-10-12收尾附记：本轮两份文档的资金流报告链接、新计划canonical hash/文件hash、原37份报告保留与git diff --check均通过。全仓check_docs_integrity在其他任务未跟踪的docs/product/xxm-macd-structure-research-v1.md报3处dead-absolute-links（带行号路径），不属于本轮文档；不改该任务文件，也不把全仓门禁记为通过。当前概念执行器、测试和两份冻结清单已完成，本开发切片因共享周线源码变动及全仓文档门禁未关闭；稳定工作区后复验，不进入正式APPLY。


2026-10-12完整复验启动：管理员要求提交并继续，上轮10文件已提交f872faaa。约90秒DG源码观察无变化，旧3处研究文档链接初检解除；catalog初检完整通过，static真实失败为新周线bootstrap模块未进入受保护源码清单。按LLD§41.5只增加该一项consumer源码只读路径，已审计32文件闭包，没有改周线业务、resource权限或policy模板；随后完整catalog/static/isolated defs重跑，并核对前后源码hash、旧40份证据/计划、两份冻结计划只读预演和全部辅助门禁。未预填切片关闭，不含正式登记/启用/加载/pool或P5。


2026-10-12最终复验完成：只补新周线bootstrap一项consumer源码只读路径，完整catalog12项/492 subtests、static113项/15批、完整隔离dg check defs全部通过；17批各7个原生负例通过，正式连接0，拒绝哨兵不变。Ruff、文档/diff/链接和CodeGraph通过，原3处其他任务研究文档链接阻塞已消失。当前工作区仍有其他任务脏文件，但709份DG源码初始约90秒无变化，门禁前后1133份源码/顶层测试hash相同，suite及defs源hash与当前工作区匹配，不存在本轮阻塞；不声称工作区干净或今后不变。

两日/495日原冻结计划正式只读重构、预演均通过，文件/hash不变，缺口仍2键/4物化/4检查和495键/990物化/40检查，completed=0。原40份报告/清单不改；资金流产品和测试hash不改，46项恢复/79项旧两表回归及495日容量沿用已提交证据。完整结果见LLD§41.6及[当前门禁收尾证据](../../reports/moneyflow_p4_cnt_ths_event_registration_closeout_evidence_20261012.json)。§46开发切片关闭；此前阻塞历史保留，但已解除。P4整体开放，P5未进入。

下一阶段技术条件已具备：按已冻结两日清单单独批准，写前确认sensor实际状态、active job、当前源码和维护窗口；正式样本读回通过后再单独批准全量。本轮只有精确源码读取清单、两份原文档和新证据改动，无主体依赖/配置/源参数/Lake路径变化，正式分区/event/Lake/staging写入、job/sensor/状态/pool/reload、来源请求和依赖安装全部0。


## 47. moneyflow_cnt_ths两日正式登记样本（2026-10-12）

管理员“提交吧，然后继续推进”承接§46下一阶段的精确两日样本；4个开发收尾文件已提交9ecce77e。按LLD§42.1先只读、再执行已冻结2026-09-29/30清单，仅2分区/4物化/4检查，每日387行。执行前后核对实际sensor状态、active job、原冻结计划/物理证明及当前实际加载源码；现有周线4文件变化不属于本次范围，旧全仓门禁保留为当时快照。

APPLY使用现有concept固定adapter与共享可恢复引擎，维护范围是sample plan_hash=728f979259727100dab6bf7598a491f64a7fd8254e3255ddfa85e93de6426d5b。写前范围、命令、成本上限、拒绝与续跑姿态均见LLD§42.1；不运行495日全量，不启用sensor，不改Parquet。两日检查target、行数/readiness、原全量清单remaining及幂等重放核验通过后归档结果，再单独进入全量阶段。整个P4保持开放，P5未进入。


2026-10-12样本执行完成：2键/4物化/4blocking check正式登记，10/10完成，两日每层774行，4条检查partition/target完全匹配，两日两层readiness均ready。同冻结样本真实APPLY重放新增0键/0事件，checkpoint complete，sensor原生状态前后不变，无active job。实际加载83份项目源码与9ecce77e及旧验收hash一致，当前并行周线变化未进入样本执行链。全部990物理文件与54控制hash、原两份计划不改；旧41份报告保留。APPLY1.4522秒/53次helper native读，不能外推全量耗时。

正式结果与边界见LLD§42.2及[两日正式样本证据](../../reports/moneyflow_p4_cnt_ths_event_registration_formal_sample_evidence_20261012.json)。§47两日样本关闭；原全量plan_hash=ff4a6fd4ab4dc4f98eb1ee479c9938a6d3076d0d95949455211f51b2c1329c77只读预演仍1525项，已有10项，剩493分区/986物化/36检查，1515项/1022事件；下一阶段按原清单单独批准。P4整体开放、P5未进入；未执行全量、sensor启用/job/reload/pool或来源请求，Parquet未改写。此次没有新产品代码、配置、契约或主体依赖变化。


## 48. moneyflow_cnt_ths冻结全量历史登记与收尾（2026-10-12）

管理员明确批准按冻结全量清单执行；§47样本记录已提交a9973d19。使用原495日full_plan_20261011.json，plan_hash=ff4a6fd4ab4dc4f98eb1ee479c9938a6d3076d0d95949455211f51b2c1329c77。目标495键/990物化/最近20来源日40检查，1525项；样本已有10项，预检剩493键/986物化/36检查=1515项/1022事件，原样本ID与检查target必须复用。

精确命令、版本/维护/预算门禁及拒绝续跑见LLD§43.1。允许同工作区无关文档提交，业务实际加载源码必须仍与a9973d19和旧验收hash一致；其他周线任务不动。全量后对账原生集合/逐日行数、40条check精确target及最近20日分批readiness，真实同清单APPLY重放新增0；全部990文件及54控制hash不变。未预填成功，不启用sensor/job或P5，整个P4仍开放。


2026-10-12全量正式执行与收尾完成：本轮新增493键/986物化/36检查，1022事件；累计495键/990物化/最近20来源日40检查，1525/1525项，全部原生差集为0。每日行数与冻结清单一致，每层192009行；40检查partition/精确target均通过，最近20来源日两层40/40 ready。两日样本4物化和4check身份不变。全量APPLY18.4033秒/141读/1166次进度回调，原checkpoint complete；真实全量APPLY重放新增0键/0事件。未放宽预算，全部990文件、54控制、两份计划及旧42份报告不改。

正式结果、性能与恢复证据见LLD§43.2和[全量历史登记收尾证据](../../reports/moneyflow_p4_cnt_ths_event_registration_formal_full_evidence_20261012.json)。只读运行态审计确认concept两个job已加载、三个sensor尚未加载，writer pool无持久化limit；没有reload/改pool/启用sensor。现有日历支持10月8、9、12切换窗口，本轮未验证源可取；12日09:42尚未到22:00，不把未登记当成日更失败。

§48及本数据集P4历史登记切片关闭；其余四表P4仍逐表待办，整个P4未关闭，P5未进入。下一步恢复其他数据集P4开发，日更加载/启用/真实源验收另分阶段明确批准。没有产品代码/配置/契约/主体边界改变，仅授权DG原生事件、staging控制与两份方案/新证据更新；保留其他任务修改和历史记录。


## 49. moneyflow_ind_dc的P4资产接入（2026-10-12）

管理员要求提交并推进东财板块P4；概念全量收尾已提交8335cf3c。本次沿实施卡先完成独立Raw/Silver、专属动态分区、两blocking check、两job、catalog/name_mapping。东财接口包含行业/概念/地域三类，以日期+类别+名称为键，代码可空，18字段/金额元保真，两轮3类分别完整分页；Silver只读同日已绿Raw并仅转日期。

编码前硬口径、消费者、配置/性能预算及验收映射见LLD§44.1～2。共用daily_update显式白名单加入DC，原THS消费者同步迁移负例前提；只补3条精确consumer源码读取路径，测试隔离策略不变。正式源/PG/Lake和job/sensor/reload/pool/事件动作均0，不推进sensor或历史APPLY，P4整体开放、P5未进入。完成情况以实际隔离与完整门禁证据为准。


§49本切片已完成：Raw/Silver、专属分区、两blocking check、两单层job和catalog/name_mapping全部接入；共用发布白名单仅新增DC，原协议及隔离策略不改。新DC专项42项、含其在内的资金流回归339项通过；归档真实样本1031行（三类496/504/31）两轮6次假源调用，Raw/Silver/check计数一致、reject0、18字段全等，两native check的同日partition和精确target读回通过。不能用虚拟时钟样本耗时代替真实网络SLA。

完整受保护catalog12项/498子断言、static113项及每批7个原生拒绝反例通过，完整隔离定义加载、Ruff、全DG致命检查和文档检查通过；1138份DG源码/测试在验收前后hash稳定，旧43份资金流报告/清单不变。范围、成本、首次失败修复和计划逐条对账见LLD§44.3及[东财板块资产验收证据](../../reports/moneyflow_p4_ind_dc_evidence_20261012.json)。本轮没有正式PG/Lake/源请求、job/sensor/reload/pool/事件动作，没有主体系contract或依赖矩阵变更，其他任务修改保留。

下一切片开发三个默认STOPPED sensor，并对P3冻结739来源日/364012行每层/1478文件做历史只读预演。历史只认冻结实际分类，不以未来日更三类非空规则拒绝早期文件。历史执行器、冻结样本/全量清单和正式登记后续独立验收与批准；moneyflow_ind_dc尚未完成整个P4，整个P4开放、P5未进入。


## 50. P4东财板块STOPPED sensor与历史只读预演切片（2026-10-12）

上一资产切片已提交872bc135，管理员批准继续三个默认STOPPED sensor及739来源日只读预演。编码前硬口径、CodeGraph消费者审计、配置/性能测算、完整命名、正反验收和正式只读范围见[LLD §45](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ind-dc-automation)。复用固定单表合同、22:00分区注册与最近10交易日单日Raw/Silver selector，不新增来源协议或全历史sensor扫描。

历史P3冻结739日/364012行每层/1478文件和实际分类不改；早期行业历史与未来三类日更新要求分开。最近20来源日深核实际分类和每日行数，其余日期通过已冻结P3文件/control hash核对；native读取分批100日期，预算19次helper查询。根据已归档95073/95049字节真实单日文件，DC readiness单独4MiB/文件，最长tick80MiB，旧三个数据集64KiB不改；超过预算拒绝hash，其他来源/内存/SQL/pool预算不改。

实施只涉及固定automation合同、三个sensor/readiness/preview及共享对应分支、专项测试、精确保护源码清单、static定义清单和两HTML标签文档。完整隔离门禁后才执行真实正式只读预演；不reload、不启用sensor、不写分区/event/Parquet、不请求源、不安装。历史执行器、两日样本/冻结全量清单另作下一切片；P4整体开放，P5未进入。本节不预填实际验收。


### 50.1 三个sensor及739日正式只读预演通过

独立三个sensor默认STOPPED并使用标准分类tags，22:00分区注册/最近10日每tick一个Raw或Silver job、有限retry、精确green check/文件hash和Silver上游修订门禁全部复用；DC单文件4MiB上限、原三表64KiB保留。历史按P3实际分类及每日row_count核验，早期单行业正例合法而同文件未来日更缺类拒绝，未计算填补已接受缺口。

303项资金流隔离回归通过，新DC50项在测试import整理后复验通过；完整受保护catalog12项/498子断言、static113项、完整隔离Definitions、项目cwd Ruff及致命检查通过，1143源码/测试快照据实区分两份新测试import整理前后，所有产品源码保持hash，旧44份报告不改。10日期实际sensor tick仅20文件/1901220B hash、7次native读取和1日历SQL、0.0253秒/cursor590B，来源调用0。

739日正式只读预演与重跑一致：364012行/层、1478文件/70542522字节、40个已关闭unit、82控制hash；最近20日实际分类与标准化160 SQL通过，原生查询19次，首次1.1672秒、重跑0.6305秒。待登记739分区键、1478物化、40最近检查，总2257项/1518事件；本轮正式写入0，未reload、启用sensor、改pool或请求源。当前源码STOPPED不等于已加载/持久化sensor状态核验。

完整硬口径对账与限制见[LLD §45.3](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ind-dc-automation)，[原生与文件证据](../../reports/moneyflow_p4_ind_dc_sensor_event_preview_evidence_20261012.json)归档。本切片关闭；下一步仅固定DC历史登记执行器及其隔离门禁、两日样本和冻结全量清单，精确写入清单仍另获批准。P4整体开放、P5未进入，其他任务修改保留。


## 51. P4东财板块历史登记执行器与清单切片（2026-10-12）

按管理员“继续推进”和LLD §45.3，接固定DC历史登记执行器，校准每日row_count/scope_row_counts消费者，进行临时native instance取消/退出/幂等/计数与739日容量验收，再生成2026-09-29、09-30样本及739来源日全量冻结清单并正式只读预检。硬口径、CodeGraph影响面、配置/性能与逐文件证明范围见[LLD §46](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ind-dc-event-registration)。

复用原plan/proof/history_events协议，20日检查、100日批、4096项/600秒/256次native读取和512MB单线程不spill预算保持；全量2257项/1518事件，隔离APPLY预计207读/1546次原子控制保存。计划不读取event ID作为身份，不另建通用来源协议。仅扩DC固定adapter与分类事实核验，不改原三表metadata/清单或主体依赖矩阵。本轮不提交、推送、正式APPLY、reload/启用sensor、pool/source/Lake/staging控制写入；P4整体开放，P5未进入。正式清单是后续审批依据，不能以“继续推进”自动执行全量登记。


### 51.1 执行器及冻结清单完成

固定DC事件PLAN/执行入口已接，共享writer新增本表每日行数、分类metadata核验，proof与检查阶段复用相同冻结分类SQL；原三表metadata、六份旧冻结清单和未来日更三类合同不改。DC57项、原链与DC sensor/preview175项全部通过；739合成日期临时SQLite完成2257项/1518事件、207次读取、1546次原子控制保存，8.2396秒、RSS437.5MiB，不外推正式PG APPLY成本。

完整受保护catalog12项/498子断言、static113项、隔离Definitions、Ruff/致命检查通过，最终1146份DG源码/测试hash稳定、原45份报告不改；CodeGraph消费者审计和根索引同步完成，其他任务修改保留，无主体依赖矩阵变更。

正式只读生成并重构[两日样本清单](../../reports/moneyflow_p4_ind_dc_event_registration_sample_plan_20261012.json)和[全量清单](../../reports/moneyflow_p4_ind_dc_event_registration_full_plan_20261012.json)：样本09-29/09-30各1031行，共2062行、10项/8事件，plan_hash=86e1014ec5fbfee902d2ff0269c379882513243502e108012b58e12bb2be4ab1，预检0.4772秒/7读；全量739来源日364012行/层、2257项/1518事件，plan_hash=c47968312063d88aa523f5e46e7e36e3d0444eb5254d7bd02e42af58d1acd417，预检0.6333秒/21读。包括旧六清单验证的驱动共6.1781秒，正式events库存、文件/control hash及旧报告保持不变。

完整硬口径对账、恢复/配置/预算和审批范围见[LLD §46](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ind-dc-event-registration)，[实际证据](../../reports/moneyflow_p4_ind_dc_event_registration_evidence_20261012.json)已归档。本切片关闭；下一步仅按两日精确清单另获正式样本批准并做维护/source/identity检查，然后登记及native读回，完整全量仍独立批准。当前没有正式APPLY、reload/启用sensor、pool/source/Lake/staging control写入、提交或推送；P4整体开放，P5未进入。


## 52. P4东财板块两日正式样本登记（2026-10-12）

管理员在两日精确清单展示后要求“继续推进吧。”，本轮授权对应2026-09-29、09-30的2分区/4物化/4检查；完整全量仍独立批准。执行前完成本表三个sensor、两个job、源码/storage/物理hash及磁盘/独占writer门禁，使用§51冻结样本和原固定执行器，写后原生事件与四readiness读回，再真实幂等重放和全量只读差分。当前任务源码以原1146份验收快照为准，不修改产品代码或依赖边界。

精确命令、读写目标、预算、恢复方式与验收映射见[LLD §47.1](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ind-dc-formal-sample)。正式Lake/Prod/Tushare不写或请求，不reload/启用sensor/调整pool/执行job；P4整体保持开放，P5未进入。实际结果在执行后追加，本节不预填完成。


### 52.1 两日正式样本通过、全量待独立批准

2分区键、4物化和4条blocking checks已按冻结样本正式登记，10/10项完成，首次APPLY1.9173秒/53次helper native读。两日每层1031行，行业496/概念504/地域31，source/checked计数及18列metadata正确；四检查精确指向对应物化，四个readiness全部ready。同清单真实APPLY重放1.7966秒，新分区/event均0，原物化身份和检查target保持；checkpoint complete/100%。

三个sensor原生状态未启用、当前定义默认STOPPED，两个job无active run；60份相关源码、83份实际加载源码和1146份原验收快照均相符，5408份冻结Lake/控制文件及48份历史报告逐字保留。正式Lake未写，未请求Prod/Tushare、reload/启用sensor/调整pool/执行job，无产品代码或依赖边界变更；本轮未提交或推送。证据及预算/恢复/验收映射见[LLD §47](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ind-dc-formal-sample)和[正式样本报告](../../reports/moneyflow_p4_ind_dc_event_registration_formal_sample_evidence_20261012.json)。

下一步可独立批准原739日冻结全量清单；只读确认已完成10项，剩737分区/1474物化/36检查，总2247项/1510事件，保持原plan_hash及样本原生身份。正式全量尚未执行，P4整体开放、P5未进入。


## 53. P4东财板块全量历史登记及收尾（2026-10-12）

管理员要求提交并继续原739日冻结全量清单；此前24个任务文件已在dev-interface提交为5883ae7a，未推送。全量只读准入确认复用样本10项，新增737分区/1474物化/36最近检查，总2247项/1510事件；不重建清单或Parquet，不填历史源缺口。维护、代码/storage/物理hash、空间和独占writer重新核验，按原逐项checkpoint执行，聚合native读回、最近5日readiness及真实幂等重放收尾。

精确命令、写入范围、600秒/256读/768MiB等预算、恢复和验收口径见[LLD §48](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ind-dc-formal-full)。本轮不改产品源码或边界，不操作Prod/Tushare、reload、sensor、pool或job。实际执行结果在完成后追加，整个P4和P5状态不提前关闭。


### 53.1 全量正式登记收尾通过

moneyflow_ind_dc的739日历史登记已完成：复用样本10项，新增737键/1474物化/36检查，最终739分区、1478物化、最近20来源日40条blocking check齐全。首次APPLY26.5388秒/207次helper native读，写后缺分区/物化/检查均0；每层累计364012行、各日实际分类及row/source/checked计数、18列metadata和精确check target全部通过。最近5来源日两层10个readiness均ready。全量真实APPLY重放5.7220秒，新增分区/event均0，全部原生身份/target及样本checkpoint保持。

首轮1723条逐项进度、checkpoint complete/2257/100%，驱动峰值RSS约413.8MiB/总39.1292秒；600秒/256读/768MiB门禁未触发。三个sensor未启用、两job无active run；60份相关源码、83份实际加载源码和1146份原验收快照一致，5408份Lake/control和49份旧报告逐字保留，其他三表原生事实摘要不变。未写Parquet或请求源，未reload、启用sensor、改pool或执行job；无产品代码/依赖边界变更。原24个任务文件已提交5883ae7a，新增收尾文档及报告未提交，未推送。

完整依据/限制和实际证据见[LLD §48](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ind-dc-formal-full)及[全量报告](../../reports/moneyflow_p4_ind_dc_event_registration_formal_full_evidence_20261012.json)。本表P4历史接入阶段关闭，历史缺口保留、checks仅覆盖最近20来源日；整个P4开放，P5未进入。下一开发切片为moneyflow_dc的独立资产/check/job/catalog，正式写入或启用仍按精确阶段清单批准。


## 54. P4东财个股定义接入（2026-10-12）

上轮板块全量收尾已提交4486b08f，未推送。本轮按管理员要求推进moneyflow_dc的独立Raw/Silver、两条blocking check、两job、专属动态分区和catalog；先核验7A卡、P2真实源、P3逐日历史、共享管线语义和CodeGraph消费者，再编码。完整硬口径、代码/测试映射、配置审计及性能预算见[LLD §49](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-dc-p4-definitions)。

复用15字段date+ts_code口径，金额万元，NULL/负值/北交所及全部源证券保留，源净流入不重算；单日2000分页两轮稳定。Silver只读同日最新绿Raw及匹配物理hash。不得套用板块三分类、可空代码或元单位。执行隔离原生job/check与6024行存档样本全字段验收，回归原链及完整受保护门禁；正式资源只读。传感器/readiness/历史预演后续分片，正式登记或日更执行按其阶段审批；本轮P4整体开放、P5未进入，不提前写完成。


### 54.1 独立定义与完整验收通过

moneyflow_dc两层资产、两条blocking checks、两job、独立分区和catalog已接入。39项原生隔离测试及683项原四表P4/七表P2回归通过，完整受保护catalog12项/504子断言、static113项、隔离Definitions加载与Ruff通过。15字段和日期+股票代码主键沿P2合同，万元/源net_amount/NULL/负值保留；存档实测6024行完整读回，SZ3154/SH2522/BJ348，8分页请求，两轮行序不同仍逐字段一致，reject0，Silver不请求源。

正式Lake仅只读复核2026-09-30两文件，各6024行/唯一键、15字段保真，文件hash与P3原证明一致，写前后不变，0.2482秒。存档样本job的1.0224秒来自fake clock和隔离SQLite，不外推盘后网络耗时。原49份资金流报告和1150份最终源码/测试快照保留；CodeGraph同步完成，Prod合同、API/前端、主体依赖矩阵不变。上轮收尾已提交4486b08f，本轮代码/文档/报告尚未提交，未推送。

详细硬口径对账及恢复/限制见[LLD §49.3](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-dc-p4-definitions)，[实际报告](../../reports/moneyflow_p4_dc_evidence_20261012.json)已归档。本轮正式instance/event/分区/Lake/staging control写入及源请求均0，未reload、启用sensor、改pool或运行正式job。本切片关闭；下一步是三个STOPPED sensor、专属readiness和739来源日有界只读预演，后续登记执行器/冻结清单及正式登记各按阶段推进。整个P4开放，P5未进入。


## 55. P4东财个股sensor/readiness和历史只读预演（2026-10-12）

上一切片16个文件已提交0e432a94，未推送；本轮按管理员明确要求，接三个默认STOPPED sensor、独立就绪判断和739实际历史来源日只读预演。硬口径、命名/tags、CodeGraph及真实consumer审计、4MiB本表预算配置审计、10日热路径与历史19次native读模型见[LLD §50](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-dc-automation)。

沿22:00上海登记当天、最多另补一个漏日、更新最近10交易日/单tick单run；sensor不请求Tushare，Silver只消费同日最新绿Raw。历史739日每层4278673行，2023-11-22缺口保留，1478文件/46unit/最近20日全字段与冻结行数核验；不把存在文件等同event ready。原四表预算/revision/清单保留，治理/拓扑HTML同步，完整受保护门禁与隔离native验证；正式PG/file/control只读。执行器、两日样本/全量冻结清单与正式APPLY留到后续，本轮不reload、启用或正式运行；P4整体开放、P5未进入。


### 55.1 三个sensor、就绪判断和739日只读预演验收完成

三个独立sensor默认STOPPED，22:00登记、最近10交易日/单tick单run、最新同日绿check及file hash、Silver绑定Raw修订、6次持久化重试和跨源cursor隔离全部通过。51项新增测试及381项原链回归通过；完整受保护catalog12项/504子断言、static113项、隔离Definitions和Ruff通过。十日窗口使用存档6024行样本及隔离原生job/check，tick顺序hash20文件/8132860B，0.0247秒、cursor570B、源请求0；本表独立4MiB文件预算不改变旧四表预算或revision。

739来源日正式预演两遍结果一致，Raw/Silver各4278673行，1478文件/585570020B与94份冻结控制hash不变，最新20日15字段/date+ts_code和冻结行数通过SQL核验；每遍19次native读取，1.6939/0.8047秒。正式最近10来源日readiness仍为file_without_materialization，未误放绿。待登记739分区、1478物化和40检查，共2257项；2023-11-22缺口保留，不造空分区。

完整硬口径对账、成本、限制与恢复边界见[LLD §50.3](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-dc-automation)及[本轮报告](../../reports/moneyflow_p4_dc_sensor_event_preview_evidence_20261012.json)。原50报告和最终1155源码/测试hash保留，CodeGraph同步完成，无Prod/API/主体依赖矩阵变更。本轮正式写入、job/sensor evaluation、源请求、reload/enable/pool修改为0；上一切片已提交0e432a94未推送，本轮尚未提交。

本切片关闭，整个P4开放、P5未进入。下一步是moneyflow_dc的可恢复历史登记执行器、隔离两日样本及739日冻结全量清单；正式APPLY和sensor启用仍分别按精确清单批准。


## 56. P4东财个股历史登记执行器、两日样本与739日冻结清单（2026-10-12）

上一切片16文件已提交06a68313，未推送；本轮按管理员要求接本表可恢复历史登记执行器、隔离两日样本和739日全量冻结执行清单。编码前硬口径、真实consumer、metadata/SQL行数守卫、逐event持久化和恢复、性能/配置与正式只读边界见[LLD §51](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-dc-history-events)。

正式样本选2026-09-29/09-30，来源6023/6024行，共12047行/层、10项/8event；全量739来源日、4278673行/层，739partition+1478mat+40最近check=2257项/1518event。两个固定bootstrap入口复用共用planner/engine，只加本表row_count验证，保留15字段与万元/NULL/负值/北交所，2023-11-22缺口保持。隔离SQLite证明取消、退出、观测故障续跑与739容量，完整受保护门禁回归旧四表；正式PG仅只读生成/验证两PLAN和既有八份旧清单。正式APPLY、sensor/reload/job不在本轮范围；本轮结果随后回填，P4整体开放、P5未进入。


### 56.1 执行器、隔离两日样本与全量冻结清单验收完成

两个moneyflow_dc固定planner/report入口已接入，复用原锁、逐event持久化、原子plan/checkpoint与native差分恢复；共享engine两处row_count守卫增加本表，旧四表metadata/plan/revision/预算保持。49项本表测试、233项原链回归通过，包括取消、实际子进程退出47、checkpoint/观测故障、错误计数/来源/hash/target及四表交叉拒绝。隔离两日6023/6024行、15字段/source与checked计数/target和四ready通过，10项/8event及幂等新增0；739日期容量2257项/1518event、207读、8.8395秒、RSS约611MiB，1546次原子保存通过。该容量为121199行合成/归档fixture，不外推正式全量写入耗时。

正式PG仅只读生成并重新验证[两日清单](../../reports/moneyflow_p4_dc_event_registration_sample_plan_20261012.json)和[739日全量清单](../../reports/moneyflow_p4_dc_event_registration_full_plan_20261012.json)，分别10项/8event、2257项/1518event；实际来源两日12047行/层，全量4278673行/层，1478文件/585570020B与94控制hash不变。默认预检样本7读/0.7806秒，全量21读/0.8694秒；旧四表八份清单hash与语义验证保持，2023-11-22缺口不补。

完整受保护catalog12项/504子断言、static113项、隔离Definitions和Ruff通过，最终1158源码/测试与旧51份报告hash稳定，CodeGraph核查/同步完成；无主系统边界、API/CLI或配置变更。详细硬口径对账、两个plan_hash、正式只读证据及限制见[LLD §51.3～51.5](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-dc-history-events)与[验收报告](../../reports/moneyflow_p4_dc_event_registration_evidence_20261012.json)。上一切片已提交06a68313未推送，本轮新修改尚未提交。

正式分区/event/file/control写入、源请求、job/sensor evaluation、reload/enable/pool修改为0。本开发切片关闭，P4整体开放、P5未进入；下一步按冻结两日清单获批后做正式样本登记及metadata/target/readiness/幂等验收，再独立推进739日全量APPLY。


## 57. moneyflow_dc冻结两日正式样本（2026-10-12，已验收）

管理员批准两日清单执行；前一开发切片10个文件已提交9f61abea，未推送。执行约束见[LLD §52](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-dc-formal-sample)。本轮只登记2026-09-29/30的2分区、4物化、4检查，并验收4个就绪结果和同清单幂等重放；两日每层6023/6024行，冻结plan_hash=5624f20348a7bb103cd620a92fce765f638c2763f74fa5a46109d06aa9c0ebbb。先查正式维护、文件、源码、storage身份和空间门禁再写入，结果另行追加。739日全量仅只读差分，不执行全量、reload、sensor启用、pool或日更job；整个P4仍开放，P5未进入。


### 57.1 正式样本验收与后续范围

两日正式新增2分区、4物化、4检查，10/10完成。09-29/30每层6023/6024行、15字段、source/checked计数及文件/cohort/upstream/plan证明一致；四个blocking check均成功，partition和storage_id/run_id/timestamp精确target读回相符，四readiness均ready。首次APPLY2.7752秒/53次helper native读，重放2.4057秒/53读且0新增键/事件、原生身份保持；checkpoint为complete/100%。55份既有报告、1158份源码、6978份冻结物理/控制文件、旧16份历史事件控制及旧四表原生事实均保持。详见[正式验收证据](../../reports/moneyflow_p4_dc_event_registration_formal_sample_evidence_20261012.json)和LLD §52.2。

本样本阶段关闭。全量仅只读预演，原739日冻结清单/hash不变，已完成10项，剩737分区+1474物化+36检查=2247项/1510事件；下一步独立批准原全量清单后再执行，保留两日样本身份/target。尚未执行全量、reload、sensor启用、pool或正式job，整个P4仍开放，P5未进入。本轮无产品代码/API/配置/依赖边界变更；本轮收尾只更新这两份文档及新增验收报告，尚未提交。


## 58. moneyflow_dc冻结739日全量登记（2026-10-12，已验收）

管理员明确批准原全量清单；两日样本收尾已提交e33a9c92，未推送。约束见[LLD §53](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-dc-formal-full)。本轮保留两日样本10项，仅补737分区、1474物化、36检查，原plan_hash=5ce84b78a5f9f9960d520400e6485ff71dd78018c85efbf19b52afd71e87642c不变。先复核维护、源码/storage、P3文件/控制及样本身份，再用既有可恢复helper登记并聚合读回；抽最近5来源日10个就绪结果和全量0新增重放，保留样本checkpoint及其他四表事实。执行后追加真实结果，只关闭本表P4历史接入，整个P4及P5仍开放，不扩展到job、sensor启用、pool或reload。


### 58.1 全量实测验收与阶段收尾

获批命令正常退出0，聊天中断后先读回原成功结果，未重新执行全量登记；补充只读复核通过。首次APPLY新增737分区/1474物化/36检查，27.5267秒/207次helper native读，2257/2257项完成；最终739分区/1478物化/最近20实际来源日40检查齐全，Raw/Silver每层4278673行、逐日row/source/checked计数及15字段、文件/来源hash和精确check target相符。最近5来源日两层10个readiness均ready。全量真实重放6.6044秒/207读，0新增键/event，1478物化和40检查的身份/target保持；两日样本原plan/checkpoint及原生记录保持。

原驱动含预检/登记/读回/重放44.1049秒，峰值RSS373.0MiB；1723条进度单调、最终checkpoint complete/100%，预算未超限。恢复后只读复核1.1942秒/21 helper读、0正式写，结果与原验收一致。56份旧报告、1158份源码/测试、6978份冻结物理/control、其他四表native身份、旧event控制及样本控制不变。证据见[全量正式验收报告](../../reports/moneyflow_p4_dc_event_registration_formal_full_evidence_20261012.json)和LLD §53.2；原冻结清单/hash及2023-11-22缺口保留，未重新全历史深SQL/readiness扫描。

**moneyflow_dc的P4全量历史登记及本表历史接入已关闭。** 本轮无产品代码、API/CLI、配置或依赖边界变更，仅更新本方案、LLD及新增报告，尚未提交；两日样本收尾已提交e33a9c92且未推送。sensor启用/reload、pool及正式job均未执行，整个P4仍开放，P5未进入。下一独立切片按原顺序进入moneyflow_ths的P4接入，本轮不开始下一表开发。


## 59. P4同花顺个股定义接入（2026-10-12）

moneyflow_dc全量收尾已提交fea34b23，未推送。本轮按管理员指令接moneyflow_ths的独立Raw/Silver、两条blocking checks、两job、专属分区和catalog。开发前已核验7A卡、P2真实13字段/5215行证据、P3的431日期物理事实及共享管线消费者；硬口径、配置审计、性能表和测试落点见[LLD§54](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ths-p4-definitions)。

每个源独立，保留latest和源net_d5_amount；金额万元、负值/NULL与全部源证券保留，不套用DC字段或自行重算。两轮单日2000分页，Silver只读同日最新绿Raw与匹配hash；逐文件原子发布和持久checkpoint。隔离原生job/check、存档5215行全字段和完整原链/受保护门禁通过后才关闭本片。正式只读抽验既有文件，历史431日期不重生成；两处已接受缺口2026-07-06/2026-07-09不补算。后续分别推进三个STOPPED sensor/readiness及历史预演，再做执行器、冻结清单与分阶段正式登记。本片不reload、启用sensor、运行正式job、请求源或写正式文件/event/分区；P4整体开放、P5未进入。


### 59.1 定义切片验收通过

moneyflow_ths独立两层资产、两条blocking checks、两job、专属动态分区及catalog均已接入。41项新原生隔离测试、五表P4/七表P2的716项回归、完整受保护catalog12项/510子断言与static113项、隔离完整Definitions及Ruff通过。存档真实5215行以两轮6页请求执行，13字段完整保真、reject0，latest和源5日主力净额保留；SH2316/SZ2899按源事实保留，构造BJ代码可支持；Silver只转日期、不请求源，Raw检查target/hash和逐文件中断恢复门禁通过。

正式既有2026-09-30两文件只读抽验各5215行及唯一键，13字段一致，hash/bytes与P3证明相符，0.2425秒、RSS155.6MiB；本轮没有写正式文件、控制、event/分区或调用正式instance。存档fixture两job的0.8763秒是fake clock/临时SQLite实测，不代表真实网络耗时。1162份源码/测试在完整验收期间保持，56份旧报告保留；CodeGraph消费者审计、同步及状态确认完成，无主体依赖矩阵、Prod契约/API/前端或配置变更。文档完整性检查与本片相对链接/锚点另行核验，不能用文档检查替代上述语义验收。

依据与完整对账见[LLD§54](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ths-p4-definitions)，[验收报告](../../reports/moneyflow_p4_ths_evidence_20261012.json)已归档。本定义片关闭；本轮修改尚未提交，前轮fea34b23未推送。下一片为本表三个默认STOPPED sensor、readiness和431日有界只读预演；之后执行器/冻结清单和正式登记逐阶段推进，两处历史缺口保留。未reload、启用sensor、改pool、请求源、安装或执行正式job；本表历史登记未进入，整个P4仍开放、P5未进入。


## 60. P4同花顺个股sensor/readiness和历史只读预演（2026-10-12）

上一切片17个文件已提交f4095071，未推送；本轮按管理员明确要求，接三个默认STOPPED sensor、独立就绪判断和431实际历史来源日只读预演。硬口径、命名/tags、CodeGraph及真实consumer审计、4MiB本表预算配置审计、10日热路径与历史13次native读模型见[LLD §55](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ths-automation)。

沿22:00上海登记当天、最多另补一个漏日、更新最近10交易日/单tick单run；sensor不请求Tushare，Silver只消费同日最新绿Raw。历史431日每层2191645行，2026-07-06/07-09缺口保留，862文件/24unit/最近20日全字段与冻结行数核验；不把存在文件等同event ready。原五表预算/revision/清单保留，治理/拓扑HTML同步，完整受保护门禁与隔离native验证；正式PG/file/control只读。执行器、两日样本/全量冻结清单与正式APPLY留到后续，本轮不reload、启用或正式运行；P4整体开放、P5未进入。


### 60.1 三个sensor、就绪判断和431日只读预演验收通过

三个独立sensor默认STOPPED，上海22:00登记、最近10交易日/每次一个run、精确同日绿check及物理hash、Silver绑定Raw修订和6次持久化重试均通过。53项新增及483项原链回归通过；完整受保护catalog12项/510子断言、static113项、隔离Definitions与Ruff通过。十日热路径hash20文件/6727180B，0.0253秒、cursor575B，tick不请求源；这是存档样本和隔离环境验收，不等于正式日更已经运行。

431来源日正式只读预演两遍一致，Raw/Silver每层2191645行，862文件/281281240B及50控制hash不变，并匹配P3原物理审计；最新20来源日13字段、date+ts_code和冻结行数通过SQL核验。每遍13次原生helper读取，1.3089/0.6583秒。正式最近10来源日仍为file_without_materialization，没有误放绿。待登记431分区、862物化和40检查，共1333项；两处接受的源缺口不造空分区或计算补齐。

逐项硬口径、代码/正反测试落点、预算、验证限制见[LLD §55](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ths-automation)和[本轮报告](../../reports/moneyflow_p4_ths_sensor_event_preview_evidence_20261012.json)。原57报告及最终1167源码/测试hash保持，CodeGraph根索引同步。正式写入、源请求、job/sensor evaluation、reload/enable/pool修改均0，无Prod契约/API/主体依赖矩阵变化；上一片f4095071已提交未推送，本轮尚未提交。

本切片关闭，P4整体开放、P5未进入。下一独立片开发moneyflow_ths可恢复历史登记执行器、隔离两日样本与431日冻结全量清单；THS正式row_count写入/读回门禁随执行器接入，不提前视为完成。正式APPLY与sensor启用按精确阶段单独批准。


## 61. P4同花顺个股历史登记执行器、两日样本及431日冻结清单（2026-10-12）

上一轮16文件已提交2c23180d，未推送。本轮按管理员要求开发THS独立可恢复历史登记入口，验收隔离两日样本及431日容量，并从正式只读事实构造冻结样本和全量PLAN。设计约束、真实实现/消费者、两处row_count守卫、逐事件checkpoint、性能预算和只读边界见[LLD §56](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ths-history-events)。

正式样本2026-09-29/09-30来源5214/5215行，共10429行/层、10项/8事件；全量431实际来源日、2191645行/层，431分区+862物化+最近20日两层40检查=1333项/902事件。保留latest与源net_d5_amount、万元/NULL/负值，接受2026-07-06和07-09缺口。固定薄入口复用原planner/engine；不扩check到更早日期、不做全历史逐日readiness。取消、进程退出、观测失败、幂等重放和431日有界读取在隔离环境验收；正式只读生成两PLAN并核验既有十份旧清单。正式APPLY、reload、启用和正式job不在本轮范围，结果验收后回填。P4整体开放、P5未进入。


### 61.1 执行器及两份冻结清单验收收尾

THS固定planner/validator与可恢复登记入口已接入；共享engine只补两处本表行数守卫，原五表合同、metadata和预算不变。50项新增及284项原链回归、完整受保护catalog12项/510子断言和static113项、隔离Definitions与Ruff通过。取消、真实进程退出、观测失败与checkpoint失败后按native事实续跑，幂等和跨源/错误计数阻断通过。

隔离两日5214/5215行，10项/8event，13字段及精确target通过，0.2756秒、重放0新增；隔离431日容量1333项/902event，4.9175秒、141读、921次原子保存、RSS580.9MiB。正式只读冻结样本和全量PLAN，预检分别7/15读，原五表十份冻结PLAN及20份event控制保持，862物理文件与50源controls hash不变；本轮不执行正式登记。

[两日清单](../../reports/moneyflow_p4_ths_event_registration_sample_plan_20261012.json)：09-29/09-30来源10429行/层、10工作项，plan_hash=c62919f2df2ecb6f925d9c121a521888b622899ae4938563d77a559af4b37147。[全量清单](../../reports/moneyflow_p4_ths_event_registration_full_plan_20261012.json)：431实际来源日/2191645行每层、1333项/902event，plan_hash=eb867fc0e4c58e8816cff0888079b3f2fc06b24230612b34b5e2eac3552d35ea。外部文件hash、全部硬口径/测试落点和成本见[LLD §56](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ths-history-events)及[验收报告](../../reports/moneyflow_p4_ths_event_registration_executor_evidence_20261012.json)。最终1170源码/测试和原58报告保持；无Prod/API/CLI/主体依赖变更。

本开发切片关闭，P4整体开放、P5未进入。下一步按精确两日清单批准正式登记及读回/幂等重放；样本验收后再单独批准431日全量，保持原plan hash及两处接受缺口。正式写入、reload、启用和job仍未执行。上一片2c23180d已提交未推送，本轮尚未提交。


## 62. P4同花顺个股正式两日登记与读回验收（2026-10-12）

上一十文件已提交b4e1a5e0，未推送。管理员本轮批准冻结两日清单的正式登记及读回。本轮只执行2026-09-29/09-30，5214/5215行、10429行/层、2分区+4物化+4检查=10项/8event，并完成同正式instance读回、4ready及真实0新增幂等重放；不修改产品代码或配置。完整命令、正式DG home、写范围、持久化sensor/active/storage/hash/空间/互斥门禁及恢复方式见[LLD §57](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ths-formal-sample)。

[两日清单](../../reports/moneyflow_p4_ths_event_registration_sample_plan_20261012.json)内部hash=c62919f2df2ecb6f925d9c121a521888b622899ae4938563d77a559af4b37147；外部sha256=cf7624f3292f026b88d3a6582c80c573666a5815461c3326636edcc34ba4ffe7。[431日全量清单](../../reports/moneyflow_p4_ths_event_registration_full_plan_20261012.json)内部hash=eb867fc0e4c58e8816cff0888079b3f2fc06b24230612b34b5e2eac3552d35ea、外部sha256=8f81291b7ddf181e4843a22ce4f398bc2abd8b70d6874d2513d2f463b9f9edd0保持；样本后只读复核预计剩429分区+858物化+36checks=1323项/894event。全量APPLY另按精确范围批准；本轮不reload/enable/job/pool、不请求源站、不写Parquet；源缺口保留，P4整体开放、P5未进入。执行结果随后回填，不预填通过。


### 62.1 正式样本验收收尾

按批准的2026-09-29/09-30清单在正式PG完成2分区、4物化、4检查，10/10项完成；两日每层5214/5215行，共10429行，13个observed_columns与来源/写入/检查计数一致、reject0。4check均SUCCEEDED/passed/blocking并精确绑定storage_id/run_id/timestamp；Raw/Silver共4ready，真实重放0新增且身份不变。首次APPLY1.9518秒/53helper读，重放1.9856秒/53读，60条进度单调、checkpoint complete10/10。

写前核验三个sensor无持久化状态、源码默认STOPPED，两job无active；执行前后及重放后的sensor库存摘要不变。原五表分区/物化/检查原生身份、7888物理/control指纹、20既有event控制、61JSON及1CSV、1170源码/测试保持；只新增本样本plan/checkpoint，无Parquet写入或源请求。固定入口直接使用批准源码和正式instance，不宣称workspace已reload或正式日更已运行。

详细命令、身份、计数、维护与恢复门禁见[LLD §57](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ths-formal-sample)，实际结果见[正式样本报告](../../reports/moneyflow_p4_ths_event_registration_formal_sample_evidence_20261012.json)。本轮复用上一片已通过的全部产品门禁，新增真实APPLY/读回/重放及文档完整性检查；API/CLI/配置/依赖边界不变。两文档和报告尚未提交，上一b4e1a5e0已提交未推送。

本样本阶段关闭，P4整体开放、P5未进入；下一阶段经独立批准后按原431日全量清单续跑，保持plan_hash=eb867fc0e4c58e8816cff0888079b3f2fc06b24230612b34b5e2eac3552d35ea。实际剩429分区+858物化+36check=1323项/894event，保留现有4mat/4check身份与2026-07-06/07-09源缺口；本轮没有执行全量、reload、启用、job或pool修改。


## 63. P4同花顺个股431日全量历史登记和收尾（2026-10-12）

上一两日收尾三文件已提交d8f3e45c，未推送。管理员本轮明确批准原冻结全量清单的执行与收尾。仅推进moneyflow_ths：431实际来源日、每层2191645行、总1333项，样本已完成10项；按native差分补429分区+858物化+36checks=1323项/894event。保留样本四mat/check及其target/metadata和样本plan/checkpoint，不改原全量hash、源缺口、产品代码或配置。

[原全量清单](../../reports/moneyflow_p4_ths_event_registration_full_plan_20261012.json)plan_hash=eb867fc0e4c58e8816cff0888079b3f2fc06b24230612b34b5e2eac3552d35ea、文件sha256=8f81291b7ddf181e4843a22ce4f398bc2abd8b70d6874d2513d2f463b9f9edd0。完整执行命令、正式DG home、native/storage/源码/blob/hash/维护/互斥/空间门禁、有界预算与恢复方式见[LLD §58](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ths-formal-full)。

先只读预检，后获批全量APPLY及同instance读回/0新增重放，再独立新只读进程复验431分区、862物化、40最近20日检查、每层行数和最近5日两层10ready。原五表事件、sample身份、7888物理/control、22既有event控制及全部旧报告/1170源码保持。只新增本全量plan/checkpoint；无源请求/Parquet写入、reload、启用、job、pool或安装。执行结果随后回填；本表完成后P4整体仍开放，P5未进入，不在本轮自由推进下一个数据集。


### 63.1 431日全量历史登记及本表收尾完成

2026-10-12按获批原清单差分完成429分区、858物化和36检查，复用两日样本；最终431分区、Raw431/Silver431物化、最近20来源日两层40检查，1333/1333项完成。Raw/Silver各2191645行，13 observed_columns和每日来源/物化/检查计数一致、reject0；40check均SUCCEEDED/passed/blocking并精确target，最近5日两层10ready。原09-29/30四mat/check及其身份/metadata/target和两个sample control保持。

正式APPLY18.8205秒、141helper读，1038进度单调至complete；实际全量重放3.9994秒/141读、0新增，全部原生身份不变。完整driver31.1796秒、RSS395.6MiB。独立新只读进程3.0577秒复验全部计数/按层行数/身份/10ready/控制通过，缺失均0。7888物理/来源控制、22旧event控制、62JSON+1CSV、1170源码/测试及旧五表原生身份保持，只新增全量plan/checkpoint。

[原全量清单](../../reports/moneyflow_p4_ths_event_registration_full_plan_20261012.json)内部hash和外部文件sha256保持，不补2026-07-06/07-09源缺口；只有最近20实际来源日检查，未扩大到更早日期。完整执行边界、逐项实际数据和限制见[LLD §58](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-ths-formal-full)及[全量验收报告](../../reports/moneyflow_p4_ths_event_registration_formal_full_evidence_20261012.json)。没有Prod/Tushare请求、Parquet写入、reload、sensor evaluation/enable、正式job、pool或安装；API/CLI/配置和主体依赖矩阵不变。

本表P4历史接入关闭；整个P4仍开放、P5未进入，六表历史事件接入已完成，剩moneyflow独立active资产/catalog及其sensor/登记链。下一独立开发片先按既有方案接入moneyflow资产/check/job/catalog并隔离验收，不在本轮越阶段执行。上一d8f3e45c已提交未推送，本轮两文档及全量报告尚未提交，其他工作区改动保留。


## 64. P4传统个股定义接入（2026-10-12）

moneyflow_ths全量历史收尾已提交03019748，未推送。按已确认方案推进moneyflow独立Raw/Silver、两条blocking checks、两个job、专属动态分区和catalog；详见[LLD§59](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-p4-definitions)。先记录硬口径、消费者、配置审计和成本，再编码和隔离验收。20字段保留源单位（金额万元、量手）及NULL/负值，净量/净额不重算；5572行存档源含348行BJ不裁剪。两轮单日2000分页，Silver仅日期转换并绑定同日最新绿Raw/hash，逐文件原子发布及checkpoint恢复。

原63份JSON报告保留，六表原定义/七表P2回归及完整受保护catalog/static/Definitions/Ruff需通过。正式仅只读抽验既有日期；不重复导出4067历史日、不写正式文件/分区/events、不reload/启用sensor或运行正式job。后续片分别完成三个STOPPED sensor/readiness与历史预演，再做可恢复执行器、两日/全量冻结清单和分阶段获批正式登记。P4整体开放，P5未进入。


### 64.1 定义切片验收通过

moneyflow独立两层资产、两条分区blocking checks、两个job、专属动态分区及catalog已接入。48项本表原生隔离测试、六表原定义/七表P2的749项回归、完整受保护catalog12/516、static113、隔离全Definitions及Ruff通过。5572行存档源两轮各3页，Raw/Silver20字段全值一致、reject0，真实BJ348行保留；净量/净额的NULL/负值不计算或补0，非法整数/精度等拒绝，取消/退出续跑和幂等修订通过。

正式既有09-30两文件只读schema/主键/全字段/hash核验通过，P3每层5572行、Raw541201B/Silver541177B不变；0.3382秒/RSS167.4MiB。1174份源码/测试在最终门禁期间保持，63份旧JSON报告保留；没有主体边界、Prod/API/前端或配置改变。结果见[本轮报告](../../reports/moneyflow_p4_moneyflow_evidence_20261012.json)与[LLD§59.3](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-p4-definitions)。正式Lake/staging/PG/分区/events写入、正式job/check、源请求、reload、sensor evaluation/enable、pool和安装均0，不能把隔离成功说成正式日更或历史登记完成。

本定义切片关闭；本表历史登记、P4整体及P5仍待后续。此前THS收尾03019748已提交未推送，本轮18文件尚未提交。下一独立片为三个默认STOPPED sensor、专属readiness和4067来源日只读预演，之后才进入可恢复历史执行器、冻结清单和分阶段正式执行。


## 65. P4传统个股sensor/readiness及4067历史日只读预演（2026-10-12）

上一moneyflow定义切片18文件已提交d93cd771，未推送。按管理员明确指令，接三个默认STOPPED sensor、专属就绪判断及4067实际来源日只读预演。硬口径、最终名字/tags、消费者、4MiB本表配置审计、10日热路径及历史85次native读取预算见[LLD§60](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-automation)，本节先于代码落档。

沿上海22:00优先登记当天/最多补一漏日，更新最近10交易日每tick最多一job，sensor不请求源。最新同日绿Raw/hash才可生成Silver，原六表预算/revision保持。历史4067日每层14089300行，217unit/8134文件及436控制证明，最近20来源日完整校验20字段/主键及冻结行数；批量查询原生事件，不把文件存在当event ready，不导出或重写历史。隔离native验证和完整门禁后，正式PG/file/control仅只读预演两遍及最近10日not-ready事实。可恢复执行器、两日/全量冻结清单和正式登记留后续，本轮不reload、启用或正式运行；P4整体开放、P5未进入。


### 65.1 三个sensor、就绪判断和4067日只读预演验收通过

三个独立sensor默认STOPPED，上海22:00登记、最近10交易日/每tick最多一run、精确同日绿check/文件hash、Silver绑定Raw修订和每日6次持久重试均通过。55项新增及593项原六表sensor/预演/执行器与本表定义回归通过；完整受保护catalog12项/516子断言、static113项、隔离全Definitions和Ruff通过。十日热路径顺序hash20文件/10823780B，0.0259秒、cursor555B、tick源请求0；是存档5572行及隔离时钟验收，不是正式网络日更已运行。

正式4067日只读预演两遍一致：每层14089300行、217unit、8134文件/2750606591B及436控制hash保持并匹配P3原物理事实，最近20来源日20字段/date+ts_code/冻结每日行数通过SQL核验。每遍85次原生helper读取，5.7461/5.0194秒。最近十日两层仍为file_without_materialization，没有误放绿。待登记4067分区、8134物化和40检查，共12241项工作。

硬口径、代码与正反测试落点、预算和实测限制见[LLD §60](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-automation)及[证据](../../reports/moneyflow_p4_moneyflow_sensor_event_preview_evidence_20261012.json)。1179源码/测试及64份旧报告hash保持，根CodeGraph已同步；不改变主体依赖矩阵、Prod契约/API/CLI/前端。正式file/control/partition/event写入、源请求、job/sensor evaluation、reload/enable/pool/安装均0。上一片d93cd771已提交未推送，本轮尚未提交。

此切片关闭，P4整体开放，P5未进入。下一独立片开发moneyflow可恢复历史登记执行器、隔离两日样本与4067日冻结清单，并接入本表row_count写入/读回门禁；正式APPLY和sensor启用仍按精确阶段批准。


## 66. P4传统个股可恢复历史登记、两日样本与4067日冻结全量清单（2026-10-12）

上一片16文件提交e22a68e3未推送。管理员批准本表执行器和冻结清单开发；代码前硬口径、真实实现/消费者、配置和性能审计见[LLD §61](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-stock-history-events)。固定moneyflow_stock_event_plan/moneyflow_events复用现有shared protocol；两日样本隔离读回、取消/实际退出/续跑/幂等和row_count校验，原六表回归及完整受保护门禁后才冻结正式清单。

4067日期/12241工作项超过现行单APPLY4096项/256读取预算，按现有预算冻结五个有序来源日期单元1000/1000/1000/1000/67；不提高旧限额或改变原六表行为。单元内仍按100日期批，只有尾单元覆盖最近20来源日检查；全量合计4067分区、8134物化、40检查/8174event，每层14089300行，最终按全范围native对账。两日sample和五单元full都不执行正式APPLY。本轮正式只读重验已有物理/控制事实，报告只写仓库，不创建正式控制目录。P4整体开放、P5未进入，执行结果验收后回填。


### 66.1 可恢复执行器、两日样本和4067日五单元清单验收通过

本表固定planner/validator、一次proof的五单元builder与默认只读publisher已接入，20字段、来源单位和NULL/负值保持；共享engine补齐冻结计数的写入/原生读回拒绝门禁。57项本表测试和384项原六表events/本表定义sensor预演回归通过，取消/真实退出/续跑/幂等和跨六表拒绝已验收。完整受保护catalog12/516、static113/15批、隔离Definitions、Ruff及1182源码hash保持通过；原六表12清单和65份旧JSON保持。

隔离两日5571/5572行、20字段、4mat/4check精确target及0新增重放通过。1000日最坏单元3040项/251读通过；4067合成日期五plan容量12241项/8174event/953读，每个单元保持4096项/256读/600秒，8313次原子checkpoint保存及最近20日40checks读回通过。该容量包含单行旧日与存档5572行样本，不能当成正式PG全量耗时或业务覆盖证明。

正式只读冻结真实2010-01-04..2026-09-30的4067来源日，每层14089300行；两日实际计数5571/5572。8134文件/2750606591B及436来源control当前hash保持；sample和五子plan完整重建两次相同，完整门禁通过后再次等值重建且全部冻结hash保持；分别7及23/23/23/23/7 native预检读取，completed0/formal_writes0。两日清单、五子清单、总清单内外hash、真实成本与执行边界见[LLD §61.3～61.4](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-stock-history-events)及[验收报告](../../reports/moneyflow_p4_moneyflow_event_registration_executor_evidence_20261012.json)。

[两日清单](../../reports/moneyflow_p4_moneyflow_event_registration_sample_plan_20261012.json)plan_hash=45aadf69d0f719f5cecf525932c6ce65a2b40b33915d201602b694d12ae63444；[4067日全量总清单](../../reports/moneyflow_p4_moneyflow_event_registration_full_plan_20261012.json)manifest_hash=578f70c1119a5cd901726c2103fd0703ac309b348c6cc4d3b3d70cc26245ea55，文件sha256=c1fcd6a100533b1a7556f832e4e52590d960884ea022a6bab484256980fd0f90。全量是同一moneyflow数据集的1000/1000/1000/1000/67来源日独立执行单元，不能把总清单当旧格式plan直接APPLY或放宽单元预算。

本开发片关闭，正式两日/全量登记尚未执行，P4整体开放、P5未进入。上一片e22a68e3已提交未推送，本轮16文件尚未提交。下一独立阶段先按冻结两日清单获批执行并读回，复核持久sensor状态、active jobs、维护/互斥/hash/空间门禁；样本真实PG成本通过后，再独立批准五单元全量。正式Lake/staging control/partition/event写入、源请求、job/sensor evaluation、reload/enable/pool/安装均0；主体依赖矩阵/Prod/API/CLI/前端不变，其他工作区修改保留。


## 67. P4传统个股正式两日登记与读回验收（2026-10-13）

上一执行器和冻结清单16文件已提交feb54805未推送。管理员批准按原两日清单执行09-29/09-30，仅最多2分区/4物化/4检查；原文件5571/5572行、20字段，不改写文件。完整命令、行数/身份/target/4ready读回、维护/持久sensor/active/writer/空间门禁、预算与恢复见[LLD §62](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-formal-sample)。

先默认只读预检，再已批准sample APPLY及实际0新增重放，最后独立新只读进程复验两日和全4067范围剩余缺口。73旧JSON/既有CSV、1182源码/测试、15608物理文件/来源控制、原六表native身份保持；只新增sample plan/checkpoint。五全量子plan及总清单hash保持，不执行全量、Prod/Tushare请求、Parquet写入、job/sensor evaluation、reload/启用/pool/安装。结果随后回填，P4整体开放、P5未进入。


### 67.1 当前阻塞与最小修正提案（2026-10-13）

实现已提交feb54805，未推送。两日只读预检通过，但另一任务随即将正式共享环境升级至Dagster1.13.26并把.venv改为软链接；正式执行在版本校验阶段停止，没有分区或事件写入。新环境完整catalog门禁被原隔离启动器的虚拟环境路径白名单拒绝，不能绕过或算作通过。

[LLD62.3](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-formal-sample)记录根因及待确认修正：原启动器仅放行已验证的当前虚拟环境精确真实路径，保持正式数据/网络拒绝与逐源码白名单，补路径反例并复跑完整隔离门禁。该修正尚未开发；门禁全绿后仍按原已批准两日清单登记和读回，不进入4067日全量。P4整体开放，P5未进入。


### 67.2 正式两日样本登记与读回完成（2026-10-13）

按原批准两日清单和随后“批准修正并继续两日登记”执行。实际SDK1.13.26/PG0.29.26/DuckDB1.5.2，升级由另一任务完成；本任务只修正2测试文件，保留正式数据/网络隔离与精确源码白名单，完整新版本门禁通过后才登记。此前版本拦截与启动器路径冲突均已解除，详细过程及验收见[LLD62](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-formal-sample)。

2026-09-29/09-30两层分别5571/5572行，合计11143行/层；正式新增2分区/4物化/4通过的blocking检查，10/10项。20字段、冻结计数、精确检查target和两日两层4项就绪均通过；实际重复APPLY新增0分区/0事件，原事件身份保持。独立新只读进程再核验全部一致。实测APPLY10.7393秒/53helper读、重放10.4997秒/53读，执行驱动45.6053秒/RSS496.8MiB，独立读回16.9933秒。15,608个物理文件、848来源控制、24旧事件控制、原六表登记及74旧报告保持，只新增本样本2个控制文件。

[正式样本证据](../../reports/moneyflow_p4_moneyflow_event_registration_formal_sample_evidence_20261013.json)保存新SDK下57+384功能回归、catalog12/516子断言、static113、I03-I08和16启动器正反案例、原生登记/实际重放/独立读回及保留证据。实现16文件已提交feb54805未推送，本轮2测试+2文档+1报告待提交；主体边界/依赖矩阵、业务数据集/API/CLI无变化。

本样本阶段关闭，P4整体仍开放、P5未进入。下一步单独批准按原4067日五单元全量冻结清单登记，实际剩4065分区/8130物化/36检查，共12231项/8166事件；每单元4096项/256读/600秒/RSS768MiB等原预算不变，逐单元准入和原生差集续跑，超限停止。全量manifest与五子plan原内外hash保持，没有进入全量APPLY，没有请求源、写Parquet、启用sensor或运行job。


## 68. moneyflow全量历史登记推进（2026-10-13）

五文件样本片已提交9f904f2e，未推送；管理员已批准原冻结五单元全量清单。执行口径见[LLD §63](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-formal-full)：先只读复核剩4065分区/8130物化/36检查，再逐child按原预算登记、读回、实际零新增重放，最后新进程全scope原生对账。既有两日样本和原六表、来源及物理数据保持；不执行或启用sensor，不运行job或请求源接口。正式结果待回填，P4整体开放、P5未进入。


全量五单元和零新增重放已完成，最终readiness因临时driver一次传20日超出现有10日窗口而停止。按LLD§63.2.1只读拆为两批收尾并独立复验，保持正式实现、冻结清单和预算，不再登记事件；原失败记录保留，结果待回填。


### 68.1 全量历史登记收尾完成

原冻结五单元全部完成；4067分区/8134物化/最近20来源日40检查原生读回齐全，两层各14089300行。原样本身份保持，本轮新增4065分区/8130物化/36检查。五单元实际零新增重放和新只读进程独立复验通过，最近20来源日两层40项readiness通过。首次APPLY合计191.017秒/953次helper读，各单元均在原预算内；完整驱动和独立复验成本见[LLD §63.3](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-formal-full)。

15608物理文件、848来源控制、26旧event控制、75既有报告、1182源码/测试及原六表native身份保持，仅新增五单元10个event控制文件。三sensor持久状态未RUNNING，无job/sensor执行或启用、reload、源请求或Parquet写入。验收见[正式全量证据](../../reports/moneyflow_p4_moneyflow_event_registration_formal_full_evidence_20261013.json)。本表P4历史接入和七表历史登记均关闭；P4整体调度收口和P5真实日更仍为后续独立阶段。两文档与此报告本轮待提交，未推送。


## 69. P4调度收尾：接续日期与sensor启用条件审计（2026-10-13）

### 69.1 当前事实与结论

上一轮七表历史登记收尾的两份文档及moneyflow全量验收报告已提交`7bcf268a`，未推送。本轮完成只读审计；[结构化报告](/Users/congming/github/goldenshare/lake_console/reports/moneyflow_p4_scheduling_continuation_audit_20261013.json)和[LLD§64](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-moneyflow-tushare-low-level-design-v1.md#64-p4调度收尾七表接续窗口与启用条件只读审计2026-10-13)记录当前代码、实例和物理证据。

上海2026-10-13 09:09，七表均需接续10-08、10-09、10-12三个expected交易日，共21个数据集日期、21个Raw及21个Silver执行；10-13当日须等22:00后登记，届时共28个数据集日期、28个Raw及28个Silver执行。接续日期没有已登记key、物理文件或物化。全部四日仍在最近10日热窗口内，窗口外差集为0；若未完成，10-08从10-22起会滑出热窗口。执行前必须按当前时间重新冻结完整差集，不能把本次四日数量当成自动扩日授权。

七表历史7804分区/15608物化/280最近检查原生身份与已验收证据一致；每表最近20来源日分成两组10日重验物理hash/readiness，280项通过。DG1.13.26已加载21个sensor、14个独立job及资产、14个blocking checks，各表分区独立、Silver依赖对应Raw。21个sensor默认及有效STOPPED，尚无持久化记录与cursor，符合未启用状态。七类daemon健康，当前服务进程配置了非空Tushare token，未打印或持久化凭据。14个job无运行记录或active run；外盘、目录、64GiB空间门槛和同设备条件满足，writer.lock未占用。本轮没有新接口请求或写盘canary，不能据此提前证明新日期源端完整、晚间稳定或当前写权限。

**P4调度收尾尚不能直接启用**，待处理三项：

| 项目 | 当前实现 / 正式事实 | 下一步范围 |
| --- | --- | --- |
| 日更分区注册起点 | 注册器仍从各表history_start补漏；会新增11个历史来源缺口的空分区，而更新只看10-01以后 | 共用注册器改用既有MONEYFLOW_SENSOR_START=10-01；历史起点/bootstrap保持；七表反例证明既有来源缺口不登记 |
| 唯一writer的专属队列 | 14个Raw/Silver均声明moneyflow_tushare_writer，但native未配置limit/slot；当前只靠全局最多1个run串行 | 经批准只设置本专属pool容量1并读回，14个Raw/Silver共用；不改变全局并发、其他pool或限流 |
| 既定的行数下降复核 | LLD§2.5要求前5个通过日期中位数/09-30回退，下降超过20%阻断；六表当前只有非空、上限、分页、两轮一致和文件合同 | Raw提升前补有界数量门禁，DC板块按类；稳定少行也阻断，大盘固定1行沿用现有约束 |

11个来源缺口为mkt_dc 1、ind_ths 4、cnt_ths 3、dc 1、ths 2，具体日期见LLD§64.4。它们属于原有Prod-only历史范围，没有全部重新验证源端是否可补，也不包含DC05-19的部分缺键。不能借启用自动补历史，源端可补与不可补的既有决定继续保留。

### 69.2 方案口径与后续步骤

本节校准§8：日更接续登记只覆盖C+1以后，不把bootstrap忠实保留的来源缺口注册成空分区；专属容量1池由14个Raw/Silver共同使用，符合共用writer.lock和实际资产定义，Silver仍是独立job/数据集而非另一个并发writer。六表数量复核是既定门禁尚未落码，不新增全市场证券池、任意放绿开关、源值推算或源接口参数。当前配置项、影响面、测试与预算及尚未实施的最小方案见LLD§64.4。

下一开发切片先修正注册起点并补齐数量下降门禁，核验metadata/receipt全部消费者，完成七表正反例、隔离性能和受保护门禁后提交。再生成最新日期差集、专属pool配置和sensor/job精确执行清单，按阶段获得正式写入批准：先设置并读回容量1；加载验收代码且保持STOPPED；登记接续日期；先mkt_dc一个成熟日完成Raw/check/Silver/check/readiness读回，再按表接续并启用其余数据集。全部差集清零、21个sensor有效RUNNING、实际job/文件/事件/check一致，才能关闭P4调度接入。P5真实日更继续按原至少3个不同交易日及失败恢复/修订口径独立验收，不由历史登记或本次审计代替。

09-30行数推算七表每个交易日两轮约32次请求，三日约96、四日约128，不含重试或新日期规模变化。21/28个Raw的60秒稳定间隔分别累计至少21/28分钟，300秒活动执行预算之和105/140分钟；排队、600秒tick、其他任务、Silver/check和重试使这些数字不能代表总墙钟耗时，ETA暂无法估算。配额按管理员决定不再审计。当前审计6.613秒、RSS318.281MiB、305次native只读操作及2次只读GraphQL，1182个源码/测试摘要与75份既有JSON报告未变；没有新测试来证明尚未实现的门禁通过。

本轮仅改两份设计文档和新增审计报告，未改源码、合同、跨子系统边界、配置或正式数据；未启用/评估sensor、发job、登记分区/events、reload、安装或推送。审计完成，修正开发、正式配置/接续/启用和P5均待后续；本轮新增审计文件尚未提交。

## 70. P4日更登记边界与六表数量门禁开发（2026-10-13）

上一轮审计两文档及报告已提交4a8ce2fa，未推送。管理员批准按§69的下一开发切片修正登记起点、补齐六表行数下降门禁并复跑完整门禁，明确先不启用sensor。实施细则、消费者、常量审计和预算见LLD§65.1～65.3。

七表注册器共用已有10-01下界，保留每晚22:00、当日优先、最多两key和STOPPED默认；历史合同起点、冻结清单及11项来源缺口保持。六表Raw正式提升前对以前五个已交付日期的物理行数取中位数，不足五个只用验证过的09-30；任何失效基线阻断，DC板块行业/概念/地域各自比较。下降超过20%保留候选且非自动重试，不提升、不发成功事件；恰好20%及增长通过。大盘恰好一行的现有门禁保持。

本开发片没有正式分区、event、job、sensor、池容量或Lake写入，没有源请求和依赖安装。完整功能回归及正式只读基线量测结果在本节后续记录；未完成的测试不计为通过。当前正式21个sensor仍STOPPED，P4整体与P5仍开放。

### 70.1 完整验收与下一阶段边界

本开发片已完成：七表登记下界统一到已有10-01，六表Raw正式提升前执行已验证数量基线及分类下降比较；不足五日用09-30，坏基线或下降超过20%阻断并保留候选。43个功能测试文件的1742项全部通过，最高单进程峰值630.203MiB；通过按文件独立进程隔离大样本后的累计内存，不改768MiB生产上限或测试断言。原受保护catalog/static/root-guard、I03—I08及启动器自身反例、隔离Definitions、Ruff和文档检查通过。

实际六表各五日共30个Raw文件与原生交付已核验，基线及成本见LLD§65.4；结束再次只读复查，21个sensor仍STOPPED、7804历史分区及最新交付保持、75份既有验收报告未变。详见[验收报告](../../reports/moneyflow_p4_daily_guard_evidence_20261013.json)。两文档同步记录实现、消费者、配置来源、硬口径—测试对账和执行边界，不改变主体依赖矩阵。

上一轮4a8ce2fa已提交未推送；本开发片尚未提交。下一步是提交本片并刷新/冻结正式配置、准确接续日期、启用及失败停机清单，之后按LLD§64.5分阶段批准执行。专属池容量仍未配置，本轮没有sensor启用、正式job或Lake写入，P4整体和P5保持开放。

验收报告sha256为486782be3790d3be0fd4cc91e77562044b8ab985ca47b3aaedf8cd8fb966c551，169,082B；本片限定37个文件，清单见报告changed_files，其他工作区修改保留。

## 71. P4容量1配置与成熟接续清单冻结（2026-10-13）

上一开发片37文件已提交6386dbd4，未推送。按本轮批准刷新窗口并冻结清单，12:41:43上海时间实际七表均缺10-08、10-09、10-12，共21个数据集日期、21待登记key及42个原Raw/Silver job/目标文件。10-13未到22点，只列候选，不包含在本次执行范围；到窗口后须另外刷新/冻结并批准。21个sensor仍有效STOPPED，7804历史日期/15608物化身份和最近280检查/物理就绪保持，11项历史来源缺口不接入日更。

已冻结[专属池容量1配置](../../reports/moneyflow_p4_writer_pool_capacity1_plan_20261013.json)及[成熟三日正式接续清单](../../reports/moneyflow_p4_daily_continuation_mature_plan_20261013.json)，详细参数、文件SHA、配置名/来源/持久化/消费者、性能预算、标准身份/恢复/停止条件和样本边界见LLD§66。池目前未配置；现有全局run上限1、run粒度及其他gold_stk_mins_qfq_writer容量1保持，不将writer.lock当作排队服务。本轮没有正式配置、分区、job/event/Lake写入、code-location reload、sensor评估/启用或源请求。

后续正式顺序为容量1设置读回、批准的代码加载、准确成熟key登记、moneyflow_mkt_dc 10-08 Raw→check→Silver→check真实首样本并停止独立验收，再分阶段批准剩余日期与其余六表接续；21个sensor全程保持STOPPED。GraphQL launchRun不提供run_id且不自动按run_key去重，必须先查标准身份、每动作一次提交，超时不盲重发；Silver key只绑定读回已绿Raw的SHA，不能执行占位符。清单观察日固定10-13，午夜、源码/日历/配置漂移或事实冲突后停止并重冻。

当前代码加载有独立阻断：共享工作区的周线任务正在新增job/ops和配置并修改bootstrap，被当前引用审计确认会进入共享code location加载范围。七表验收代码未变，本轮保留这些他人修改，不加载或通过别的工作区规避；待其收尾、明确加载范围并重新核验源码和窗口后，才能发布可正式执行的版本。当前是目标/请求冻结完成，不能宣称具备立即全量启动条件。

只读审计6.669秒/338.656MiB，六表30个基线文件与120条SQL验证通过；65份请求在现有GraphQL schema中静态验证，无resolver执行。三日源请求估算96次，Raw活动预算之和105分钟、稳定等待下限21分钟，整段ETA暂无法估算；账户配额不再审计。报告见[冻结证据](../../reports/moneyflow_p4_continuation_freeze_evidence_20261013.json)，本轮3报告/2文档尚未提交，P4整体和P5保持开放。


## 72. 共享工作区与加载阻断复核（2026-10-13）

管理员本轮要求先提交，再检查共享工作区是否稳定和加载阻断是否解除，仅在具备条件后刷新七表接续窗口、重新冻结可执行清单，保持sensor停用。上一轮3报告/2文档限定提交已完成：`a5e18e44af7927378dfe34b6c2e578f742f68cf5`，未推送，其他修改保留。本轮只新增复核报告并更新两份原设计文档，不改正式代码、配置、API/CLI或依赖矩阵。

13:31:29上海时间，746项源码/项目配置摘要与上一轮冻结完全相同，七表1742项验收对应的129项源码摘要没有漂移；本次审计前后源码和待加载清单也一致。**这只能证明短时间内没有改动，不能证明共享开发已验收收尾。** 5份tracked周线bootstrap/共享configs仍有未提交修改，jobs/stock_weekly_event_backfill.py和ops/stock_weekly_bootstrap_checks.py仍为untracked。当前definitions.py依旧通过load_from_defs_folder加载同一defs目录；新job导入新op，新op消费StockWeeklyBootstrapEventChecksConfig及周线bootstrap，周线/月线CLI也引用已改模块。因此上一轮加载阻断仍成立，不把“文件hash暂时没变”当作可以重载的依据，也不覆盖他人文件或切换临时工作区规避。

正式服务两次只读读回一致：21个moneyflow sensor默认/有效均STOPPED，14个job仍在，新增周线raw_stk_period_bar_adj_week_event_backfill_job尚未加载。原生PG连接确认transaction_read_only=on；moneyflow_tushare_writer仍没有limit或slot、pending0，其他gold_stk_mins_qfq_writer显式容量1保持，全实例active runs为空。没有进行重载来验证未验收的周线代码，没有正式pool/分区/event/Lake写入、job提交、sensor评估/启用、Tushare请求或依赖安装。

本轮条件检查不通过，**不进入日期窗口刷新及新可执行清单冻结**。原三份冻结文件SHA保持，仅作为12:41观察的历史目标/请求证据；不能将其旧日期、观察日run key或有效期自动延期。待共享周线改动收尾、明确加载范围后，重新核验完整源码摘要、日历/成熟窗口、原生/文件差集、pool/active/writer维护条件，再冻结剩余范围；容量配置、正式加载和首样本仍按阶段执行，不启用sensor。

完整证据见[共享工作区与加载阻断复核报告](../../reports/moneyflow_p4_shared_workspace_recheck_20261013_133129.json)，sha256=934a1d0500c05d27037b3aa4b98f488a2bc288ba1a799d2ecfdc2275c7283994，124,975B。成功只读阶段实测0.542秒/RSS177MiB，2个只读GraphQL、4条SQL、1次有界active run读取；此前临时查询缺少闭合括号返回HTTP400，已定位并经本地schema校验后修正，合计3个只读请求，未执行任何mutation。CodeGraph explore用于共享job/op/config/加载入口分析，泛名索引未完整覆盖新周线符号，缺项以当前源码和import引用核验补足。阻断明确保留，不以文档或GraphQL静态校验替代正式加载验收。P4整体与P5仍开放。


### 72.1 共享开发提交后的复验与可执行清单重新冻结

本轮结束检查发现另一周线任务已提交`5a25e578cb4f45998fe58a8a5666da982b42f4da`，此前7项源码全部纳入该提交，orchestrator/src没有未提交文件；前节13:31的阻断记录保留为当时事实，已由本节后续复核取代。周线提交对应当前job/op/config源码及正式补录结果见周线原LLD A21，记录193项专项验收、真实样本及全量读回；本任务没有重新执行周线job或改变其自动化状态。共享根分支仍dev-interface，其他Web/研究修改不进入此code location的加载范围。

重新核验当前definitions.py及新增周线job→op→config/bootstrap引用：defs按原load_from_defs_folder加载，新周线入口是手动job，不新增自动触发器。使用现有项目环境、隔离/private/tmp DAGSTER_HOME和无正式凭据的环境运行`dg check defs --use-active-venv --no-check-yaml`，exit0/All definitions loaded successfully，日志sha256=bd69366b36ad5660d01287093fbb54f56a4260e8584ae7213c233675486feb1a。本次实际加载解析包含新周线定义；不将其他任务文档或源码“已提交”单独当作加载验收。CodeGraph根索引已sync/status正常。七表1742项原验收对应129项源码/测试摘要仍完全相同，没有重跑已有功能测试或安装依赖。

13:34:46上海时间正式只读刷新：七表都缺10-08、10-09、10-12的登记/Raw/Silver交付，共21key、42目标文件/原job/物化/准确绑定blocking check；10-13未到22点仍只列候选，排除当前执行范围。四日均在现有10日热窗口内；不扩大窗口或把11项来源缺口接入日更。7804历史key/15608物化身份和最近280check/物理就绪保持。21个已加载sensor默认/有效STOPPED、14资产/job/check合同仍准确，当前服务尚未重载新源码。全实例active0，writer锁未占用；目标池未配置/pending0，其他gold_stk_mins_qfq_writer显式容量1及全局run上限1/run粒度保持。正式根/staging同设备且空间门槛满足，没有写canary。

新清单以当前已提交源码5a25e578及746项源码/项目配置摘要冻结，dependencies_dirty_at_freeze为空、source_reload_blocked=false、workspace_loading_condition_cleared=true；**原共享源码加载阻断已解除，可执行范围和请求已重新冻结，但尚未应用配置或启动任务。** 原三份目标清单和前节阻断报告均保持原SHA，不覆盖或延期它们。

| 新冻结文件 | SHA256 | 字节 |
| --- | --- | ---: |
| [专属池容量1配置](../../reports/moneyflow_p4_writer_pool_capacity1_refrozen_plan_20261013.json) | bf14ac492260460c072224904562ec45b58323561c53d510403552a70cc316e1 | 119,956 |
| [成熟三日正式接续](../../reports/moneyflow_p4_daily_continuation_mature_refrozen_plan_20261013.json) | 644066a66d5665b8e5f317371032b7eccb46eadce2732d845fa0280dc84af56b | 307,347 |
| [重新冻结与只读证据](../../reports/moneyflow_p4_continuation_refreeze_evidence_20261013.json) | 1d72e8be8d48e72a7faf61e80d834c3cc88676c0394bb0288dc3ce9ae9a7f948 | 254,982 |

顺序和恢复沿用§66/方案§71的已确认规则：按阶段批准设置容量1并读回、加载这一准确源码并确认七表21sensor仍STOPPED及手动周线入口正确；只登记获准的成熟key，先moneyflow_mkt_dc 10-08一个key/Raw→check→Silver→check首样本后停止独立验收，再批准剩余范围。原完整job、不选op/check、标准Raw身份、Silver只绑定当前已绿Raw SHA、GraphQL每动作单次提交及超时先读回、native差集续跑和既有预算保持。不能把清单标记可执行理解为本轮已批准正式写入；apply_authorized仍false，ready_for_formal_launch_now仍false，仅剩容量/加载/晚间窗口/首样本等既定阶段门禁。21个sensor全程保持STOPPED。

清单观察日10-13，正式Raw/Silver最早22:00；有效期仍10-14 00:00上海时间。到22点并不会自动把10-13加入本次范围，若纳入须重新刷新/冻结并批准；跨日或源码/日历/配置/目标差集漂移停止下一动作，保持已完成事实。本轮没有reload、pool配置、分区/event/Lake写入、job或sensor评估/启用、Tushare请求或安装。

本次完整只读刷新7.743秒/RSS352.656MiB、314个有界helper/asset/run读和3个只读GraphQL；原400读/300秒/768MiB门槛内，六表30基线文件共120SQL通过，81份既有moneyflow报告摘要保持。65份pool/reload/登记/job请求在安装版本GraphQL schema中纯语法/输入类型校验通过，没有resolver执行。成熟三日估算96源请求，Raw硬上限合计1344、活动预算合计105分钟、稳定等待下限21分钟，总墙钟ETA仍暂无法估算；不审计配额、不增加预算。P4整体与P5仍未关闭。

## 73. 专属池、代码加载与moneyflow_mkt_dc首样本推进（2026-10-13）

上一轮6文件已提交5424ccd0，未推送。管理员明确批准§72.1新清单的容量设置/读回、冻结源码加载及大盘首样本，21sensor保持STOPPED。精确执行卡、命令、正式HOME/endpoint、逐请求持久化、恢复与停止条件见LLD§68；仅10-08一个key/两个完整job，不进入其他日期或六表。13:44正式预检通过；当前source_job_not_before仍22:00，先完成容量与加载，首样本不得自行越过时点。正式结果随后读回回填，P4整体与P5仍开放。

### 73.1 批准现在处理10月8日的大盘数据

容量设置和代码加载已经读回通过，自动更新保持关闭。管理员随后明确答复“现在执行”，仅允许这一次手动处理10-08大盘数据提前开始；每天自动更新仍为22:00，其余日期/六表不执行。原清单和全部检查/预算不改，单次批准及完整命令见LLD§68.2。完成原始数据下载、整理文件及两层检查并读回后停止，不借此开启自动更新。正式结果待回填。


### 73.2 已完成的设置和代码加载，以及当前停下的原因

管理员本轮批准设置、加载和处理10-08大盘数据，随后明确答复“现在执行”。上一轮4报告/2文档已提交5424ccd0，未推送；本次时间许可已记录，后续无需再问是否允许现在处理这一天。

13:47:34完成后台“一次只运行一个资金流任务”的设置，原生moneyflow_tushare_writer显式limit1、一个未占用slot、pending0读回正确；其他gold_stk_mins_qfq_writer容量1和全局设置保持。13:47:54完成DG代码加载，serverId实际变更、手动周线任务已加载、14资金流资产的任务/分区/检查/依赖准确、21个自动触发器都保持STOPPED。前后新只读进程确认7804历史日期、15608物化记录、最近280检查和280份文件就绪保持，84份既有报告SHA保持。

准备登记10-08日期时，其他开发又修改了共用的checks/adj_factor_checks.py，并新增bootstrap/stock_adj_factor_history_repair.py及stock_adj_factor_history_repair_candidates.py；对应测试也仍未提交。修改包含正式复权因子检查函数，不是单纯文档。当前工作区代码已经与本次批准的完整摘要不同；虽然129项资金流源码/测试摘要没变，也不能绕过整个DG加载和运行的代码一致性要求。依据根AGENTS第29项保持当前工作区，不使用别的分支/worktree、不覆盖或移走其他人的改动。

登记driver在任何写请求前停下；紧接着的Raw driver也被同一检查拒绝，在发送请求前停止。13:59:43独立只读确认大盘仍839日期，10-08未登记，两层目标文件都不存在、物化0、两个资金流任务运行记录0。没有请求Tushare、写文件或补造成功记录；两个临时driver退出不能说成正式任务运行失败。一次只运行一个任务的设置和已经完成的代码加载保留，全部自动更新仍关闭。Silver没有提交，这一天尚未验收完成。

本轮新增[设置、代码加载与大盘执行结果报告](../../reports/moneyflow_p4_pool_reload_market_sample_evidence_20261013.json)，sha256=18e566ea5e769f19e110d73fd0c159aae7e1a1ca2a009e35e5b8749f2d8719bc，469,325B，并更新两份原设计文档，尚未提交。报告保留准确请求/原生响应、加载前后serverId/资产、两次历史审计、最后独立读回和“现在执行”的批准；正式变更只有一次容量setter和一次代码加载，日期/任务/数据写入都是0。文档及报告不改变代码、API/CLI或依赖边界。

下一步先等复权因子开发收尾，再核对完整代码和加载范围、更新本次允许运行的版本及实际日期/文件差集，然后只完成10-08大盘下载和整理验收。当前不能继续使用已漂移的代码，也不自动扩大到余下20日期单元；整个P4和P5仍未完成。


### 73.3 再次检查另一项开发是否完成（2026-10-13 14:11）

管理员要求先提交，再检查代码是否稳定；具备条件才继续10-08大盘下载、整理和检查，自动更新保持关闭。上次3文件已限定提交cdfed8af，未推送，其他修改保留。

直接读取“周线月线dg集成”当前任务，仍为active/inProgress；该任务正在处理25股历史复权因子及下游修复，目前还在明确旧数据问题的检查范围。当前Git代码也证实未完成：adj_factor_checks.py仍未提交（91行新增/116行删除），两份历史修复工具及测试未提交；检查期间又出现stk_mins_qfq_macd_kdj.py的修改。完整代码与上次批准版本有4项文件差异，129项资金流源码/测试本身保持，不能据此忽略共用代码尚未完成。

14:11:10新只读进程确认一次只跑一个任务的设置保持（显式limit1、一个未占slot、pending0），全active0；21个资金流自动触发器默认及有效均STOPPED。大盘仍839个已登记日期，10-08尚未登记、两层文件都不存在、物化0、两项任务均无运行记录。旧84份报告与上一轮执行报告SHA保持，本轮没有新增日期、提交任务、请求Tushare、写Lake、重载代码、配置池或安装依赖，也没有去修改另一项开发。

本轮条件不满足，按根AGENTS第29项和原方案的代码一致性要求停止，不换工作区或越过检查。时间许可已获得，不需要再次问是否能立即处理历史数据；下一步等共用代码开发完成、核对实际版本及加载范围后，再只处理10-08大盘。当前这一天仍未验收，P4整体/P5未完成。

证据见[开发完成情况与大盘状态检查](../../reports/moneyflow_p4_market_sample_development_recheck_20261013_141110.json)，sha256=fe5bc83545d02b43baf6996b68490126a404d86ccecbe6b18b54442e2bf9e1eb，113,612B。本轮只新增此报告及更新两份原文档，尚未提交；不改代码、API/CLI、依赖边界或正式数据。


## 74. 10月17日审计后的下一步

管理员批准按审计结果继续：先恢复停止工作的DG后台，再更新过期清单和临时执行检查，最后只完成10-08大盘资金流样本。具体命令、服务影响、源码检查、预算、续跑和验收见LLD§69。复用现有PG/CH/隧道和已设置的一次只跑一个资金流任务限制；恢复原来已开启的其他调度，资金流21个自动更新触发器保持关闭。

10-17实际待办为七表×10-08、09、12、13、14、15、16，共49个数据集日期/98个任务；本轮不自动执行其余48项。旧三日清单保留历史身份，由当前源码/日历/实际状态生成新清单。稳定的无关未提交修改不再一刀切阻断，实际依赖变动、加载错误、配置/日历漂移及并发写入仍会阻断。手动历史样本沿用管理员“现在执行”许可，每日日更22:00保持。P4整体/P5保持开放，正式结果待读回后登记。


### 74.1 10月8日大盘样本已验收完成

本轮恢复DG后完成一个正式日期：moneyflow_mkt_dc / 10-08的Raw下载、Silver整理和两项原有blocking check全部成功，实际两次Tushare请求/零重试、两轮间隔60.167秒，两层各1行15列且逐字段转换核对一致。只新增一个登记日期及两个完整任务；原7804历史日期/15608物化、最近280项历史检查和物理交付保持，未执行其余48个数据集日期。后台7项心跳持续正常，全部113个已加载sensor开关首尾保持，资金流21个仍关闭。

正式执行、检查与文件摘要详见LLD§69.5及[验收报告](../../reports/moneyflow_p4_environment_recovery_market_sample_evidence_20261017.json)。本轮只新增当前接续清单/验收报告并更新两份原文档；没有改正式源码、配置、API/CLI或依赖边界，没有提交/推送。当前隔离加载、检查脚本8项测试与实际正式执行分开记录；此前1742项不冒充本轮复跑。后台最初停止的触发原因尚未确认，成熟历史样本也不能替代P5当天真实日更验收。

按首样本验收边界停止，下一阶段为大盘剩余6天及另外六表各7天，共48项/96任务；之后再处理自动更新启用及P5。执行时以新的实际日期和缺口为准，保持原来每晚22点日更规则，不能默许跨日延用本次清单或直接打开sensor。


<a id="moneyflow-continuation-design"></a>

本步输入细化：日期白名单同时引用一份有摘要的只读核验证据，绑定当前依赖源码、日历、实例配置、实际加载和隔离Definitions报告；精确格式见LLD§70.3～70.4。它不代替管理员执行批准，也不引入新业务配置。

开发实测校准：动态分区集合名与原生run的`dagster/partition_set`标签须分别验证；后者使用`<job_name>_partition_set`。完整任务生成的两个执行步骤也须按实际生产者核对，详见LLD§70.4；七表原任务合同不变。

## 75. 下一步开发：七表按日期接续执行工具

本节把上一轮工作提纲补成可落地设计，实施细则统一见[LLD§70](dagster-moneyflow-tushare-low-level-design-v1.md#moneyflow-continuation-lld)。开工前一轮只完成设计和审计对账；用户随后批准提交并继续开发。**本步开发验收及大盘10-09正式单日验证已完成，最新结果见§75.11与LLD§70.19；§75.6、§75.8保留此前失败及准备记录。** 已完成的大盘10-08验收继续有效；剩余47项全量接续尚未执行。

### 75.1 要解决什么、保留什么

现有临时脚本只能处理大盘一天，且把1行15列写死。下一步增加一个有明确日期清单的命令行工具，逐表逐日调用原有Raw/Silver完整任务，检查真实交付，能够在工具退出后找到上次任务继续观察，并跳过已验收日期。它不直接请求Tushare、生成文件或补造事件；下载、分页、质量检查和候选提升仍由现有正式任务完成。

七表仍是七个独立数据集；字段、单位、来源、证券范围、路径、质量阈值、日更22:00及历史来源缺口处理保持。此步资金流21个自动触发器全部关闭，其他现有调度不动；不改Prod、BIYING、Web、ClickHouse、API、资源默认或依赖。不把完成文档当作允许执行数据。

按10-17 14:18验收，剩余范围如下，实际执行前须重新取真实差集：

| 顺序/数据集 | 已知待接续日期 | 数量 |
| --- | --- | ---: |
| 1 moneyflow_mkt_dc | 10-09、12、13、14、15、16 | 6 |
| 2 moneyflow_ind_ths | 10-08、09、12、13、14、15、16 | 7 |
| 3 moneyflow_cnt_ths | 同上 | 7 |
| 4 moneyflow_ind_dc | 同上 | 7 |
| 5 moneyflow_dc | 同上 | 7 |
| 6 moneyflow_ths | 同上 | 7 |
| 7 moneyflow | 同上 | 7 |
| 合计 | 48个数据集日期、96个完整任务 | 48 |

已完成10-08不重跑；已绿Raw只补Silver；新成熟日期只列后续建议，不悄悄追加。历史缺口不能混进来。其他六表每表第一天先完整验收，通过后在获准的同表范围连续处理，不为每一天重复制造审批步骤。

### 75.2 执行中必须按什么规则做

| 情况 | 处理决定 | LLD依据 |
| --- | --- | --- |
| 七表字段、主键和覆盖不同 | 分别引用现有固定合同和完整检查，不复制大盘判断，不仅比列数 | §70.2、70.4 |
| 工具中断，上次任务仍在跑 | 先找到并核对原run_id，只继续等，不再提交 | §70.7 |
| 下载完成、整理还没开始 | 核对Raw文件/物化/check/来源证明后只提交Silver | §70.4、70.7 |
| 两份工具同时启动 | 独立工具锁只放行一个；不占住正式job的写文件锁 | §70.6 |
| POST超时或响应没保存 | 先按原请求身份读回；唯一且准确匹配才能接回，不明时停止，不能盲重发 | §70.6、70.7 |
| 正式任务失败、文件已落但交付不完整 | 保留现场并停止，不自动换run_id复用旧候选、补绿事件或跳过坏日期 | §70.7 |
| 跨午夜或清单过期 | 停止新动作，读回已有任务；新清单继承根记录目录和已提交身份、只保留剩余范围；原业务授权仍覆盖同一范围时不重复请示，明确限期或扩范围除外 | §70.5 |
| 其他正常调度在工作 | 当前一个资金流任务进入原队列等，不停其他任务、不改优先级/并发 | §70.8 |
| 停止工具或观察超时 | 停止领取新动作，记录后台原任务状态；不自动取消job或假报日期完成 | §70.8 |
| 源码或加载状态变化 | 检查真实依赖和加载影响；相关变化阻断，无关稳定修改不一刀切；不自行reload | §70.9 |

“可恢复”只承诺找回已有任务和跳过已验收工作，不包含自动修复失败任务。这是本步确定范围，不能等执行失败时临时发挥。

### 75.3 开发落点、预算与验证

新工具为`orchestrator.moneyflow_continuation_cli`及`orchestrator/moneyflow_continuation/`包，位于defs扫描范围外，职责拆为合同、计划、只读状态、提交持久化和执行编排；拟定文件、参数、存储、默认值、消费者和测试逐项见LLD§70.3。工具只读现有合同并调用本机原完整job；没有新的资产/表/正式配置，不修改已有CLI。受控请求记录位于正式staging的独立continuation目录，不是另一份数据完成事实源。

按已知范围估算约222次Tushare请求、约12.8万行/层、96个正式文件；两轮等待累计至少48分钟。每个Raw仍最多64次请求/300秒/768MiB，DuckDB仍512MB/1线程/no-spill；资金流一次一个任务，其他正常任务走原队列。Raw活动预算合计4小时不包含排队/整理，不能作为整批完成时间。计划/汇总读≤400次/300秒；执行每日最多5个转换、每转换≤40次有界读，每原任务观察≤120次/20分钟，当前48项对应执行读上界21120次，重启不重置预算。计划条数、文件/控制记录、磁盘和每查询上限见LLD§70.10；超限停止，不自动放宽，不再审计账户配额。

LLD§70.11的C01～C13把硬口径映射到具体实现和独立正反测试，覆盖七表合同、部分完成、双进程竞争、HTTP结果不明、进程退出、跨日、本人active、正常排队、文件/事件不一致、失败停止、数量/分类下降、预算与不启用sensor。旧8项文件检查和1742项历史测试不能冒充新工具测试通过；底层同operation_id恢复也不能冒充正式新run重试正确。

### 75.4 开发和正式执行的分界

以下保留阶段划分；其中“本轮”描述写设计时的授权，当前开发事实以§75.6为准。

1. **本轮先完成设计。** 原方案/LLD给出处理决定、文件职责、配置审计、性能上限、状态表、测试和验收；逐项回应前次D1～D8，不能只写“支持续跑”。本轮没有代码或正式数据动作。
2. **下一步开发工具。** 在已有设计确认规则满足后，先做计划/状态判断，再做锁/请求记录/单次提交，最后接编排/CLI。相关回归、隔离Definitions、Ruff、文档检查及C01～C13对账齐全后，才报告开发完成；未覆盖的边界不能默认算通过。
3. **正式工具样本单独执行。** 建议新工具只处理大盘10-09一天：Raw提交后正常停止工具，再接回同一run，完成整理和检查；同清单再次调用应新增0请求/0任务。该动作需明确正式批准，本轮未批准。它补的是新工具恢复边界，不重做10-08。
4. **样本通过后按获准清单逐表接续。** 第一日验收、剩余日期连续处理，按真实交付跳过已完成；不因一个日期失败自动扩大到修复/覆盖。最终原生/物理证明和未完成原因全部读回。
5. **后续仍有自动更新启用与P5。** 完成数据接续后再按原规则逐表启用，至少观察3个真实交易日；这两步在执行前也必须补齐对应方案/LLD和审计，不能用本工具设计代替。

### 75.5 方案审计结论

开工前已按当前代码和消费者复核D1～D8，每项均在LLD§70.13列出处理决定与需取得的证据；CodeGraph用于现有合同、writer、readiness影响面分析，索引不能证明的临时脚本、原生请求和失败恢复用当前源码补足。该次结论仅为设计补齐；后续实现和验收更新见§75.6。其他周/月线修改不纳入资金流任务；正式加载条件必须届时重新核验，不声称共享工作区已重新验收。

前次单日报告、49项旧清单及历史实施记录保留，不能改它们的授权字段来取得新执行范围。新问题、范围或合同变化必须先同步本节与LLD§70并满足确认规则，之后再开发；不得恢复临时脚本或造第二条执行链绕过。

### 75.6 2026-10-17开发交付与未通过项（修正前记录）

以下保留发现问题时的事实；当前修正及验收结果以§75.8为准。

设计及根规则已提交`d631ae974`，未推送。随后按本节新增七表接续命令行工具，代码位于Definitions扫描范围之外；没有修改原七表asset/job/check/sensor、共享资源、源请求或既有入口。新增99项测试通过，相关既有回归267项通过，七表均完成真实job/check/Parquet的隔离链路及重复调用零新增验证；当前Definitions在无正式凭据、临时instance下加载成功，Ruff新文件及全项目致命错误检查通过。新工具还只读核对了正式环境已验收的10-08大盘一天，9次原生读取准确找回两层文件、成功运行和绑定的检查，新增源请求/任务/数据写入均为0。

**尚不能收尾，原因有两项：** 目录治理及run-contract静态检查使用的受保护启动器仍读取已被`09ea909fd`清退的周线文件，在断言开始前退出；根目录清退检查把10-13历史报告里保存的测试名称当成运行代码，命中关键词。它们均已用原启动器实测；没有放宽启动器、删除历史报告或绕过检查。此前开工审计未发现这两项测试基础设施问题，现补入本步未决清单。

完整证据与C01～C13逐项对账见[开发验收报告](../../reports/moneyflow_p4_continuation_development_20261017.json)及LLD§70.14。下一动作是先明确两项门禁的修正范围和正反测试、补齐对应方案/LLD及既有确认要求，再修正并复跑原门禁；通过前不运行新工具的10-09正式样本，更不执行48项接续清单或启用自动更新。原计划的正式样本、逐表接续及P5顺序不变。

### 75.7 两项检查修正与复验（用户已批准）

2026-10-17用户明确要求核对周线旧文件是否还有必要、修正B1/B2并复验。已确认周线旧实现由`09ea909fd`清退、现行历史链转到stock_period；旧文件无须恢复。按LLD§70.15从原consumer白名单删除6条已删除路径，补入当前真实定义审计依赖的5个周/月线Silver模块，只授予精确文件读取，其余隔离/网络/正式数据限制不变。根门禁只把既定reports目录内的JSON当作报告数据，继续扫描该目录的执行脚本及正式目录的运行配置；新增正反测试，保留历史报告原文。

修正后用原启动器复跑目录治理、静态、asset-check增量治理、根门禁及I03～I08，并复验资金流新工具、当前隔离Definitions、Ruff与文档。通过才关闭B1/B2和本步开发收尾；测试通过不等于正式10-09样本或48项历史接续已经运行。精确实现位置、配置消费者、失败/中断规则、预算和验收均以LLD§70.15为准。本轮不修改周/月线业务逻辑，不清退整个受保护启动器。

§75.7复验补充：目录治理恢复后，发现静态套件一处按固定换行匹配元组的旧断言。实际目录合同未变；按LLD§70.15补充改为AST核对唯一赋值及原单一检查值，保留全部113项测试和独立正反样本，不为通过测试改业务代码。

增量治理复验也发现旧测试矩阵漏登14个资金流资产及公告Raw资产；按已审计的实际blocking/readiness/保留口径补齐测试记录和真实消费者识别，原业务检查及事件保留策略不变，保留周/月线他人修改。详见LLD§70.15增量治理补充。

收尾期间检测到周/月线新readiness模块及两个合同修改，已审计与资金流无业务交叉，但需更新全定义审计的精确文件权限并重新验证当前加载；不再沿用旧加载摘要。详见LLD§70.15当前工作区刷新。

### 75.8 修正及复验完成，进入单日样本准备

§75.7及LLD§70.15的修正已完成：旧周线6条失效白名单项已移除，现用6个模块按精确文件补齐；历史报告误报消除，执行脚本/运行配置仍受检查。复验中发现的固定换行断言和治理矩阵漏登也已按真实合同修正，没有为通过测试修改业务代码或历史证据。

目录治理12项、静态113项、增量治理6项、根门禁24项逻辑用例（全部8切片）及I03～I08均通过；资金流新工具与库存测试共107项通过，当前隔离Definitions加载和Ruff通过。详细对账、代码摘要、日志及源码变化限制见[复验报告](../../reports/moneyflow_p4_continuation_gate_recheck_20261017.json)和LLD§70.16。**本步开发验收已收尾，P4正式接续尚未完成。** 周/月线仍有并行修改，资金流113项依赖在本次收尾核对一致，无关变化单列，正式动作前重新核对加载依据。

已向前推进只读准备：确认10-09大盘日期成熟且尚未登记/交付，21个资金流自动触发器仍关闭，资金流池容量1且空闲。下一阶段仍是§75.4/LLD§70.12的一天正式样本，需该阶段的精确执行清单、正式加载核对及批准；本轮未提交正式任务、请求源或写湖，也未扩大到48项全量接续。

§75.8末次核对：复验通过之后两个共享period合同再次变化，旧加载摘要失效；本次修正测试代码未变，通过记录继续有效。复验报告已追加精确变更路径与时间，正式执行就绪为False。下一步须在周/月线源码稳定后更新受影响验证和正式加载绑定，随后才可提交10-09样本；本轮没有用旧摘要启动正式任务。

### 75.9 继续完成大盘10月9日单日验证（2026-10-17）

用户本轮要求提交修正并继续推进，承接§75和LLD §70.12的下一步。本次只处理 `moneyflow_mkt_dc / 2026-10-09`，先登记日期，再用已提交的新工具完成下载、停止工具后接回同一个后台任务、整理与读回；再执行同一清单，验证没有新增任务或来源请求。不得扩到另外47项，不开启21个自动更新，不修改周/月线、并发配置或重新加载服务。此处是正式单日操作，不能写成隔离测试结果。

当前源码审计确认84份已验收资金流代码摘要全部保持；共享路径3个、字段定义14个、目录相关35个AST节点与已验收提交相同。周/月线新函数没有进入资金流调用链；当前113项依赖全部重新记录，不排除共享文件。当前源码隔离Definitions加载通过，737份源码加载期间稳定；正式服务14个资金流资产合同与21个停止状态吻合，serverId为906ed8b6-8fd2-4f1f-b724-3ce491b35e69。新工具不在Definitions扫描目录，无须为它重新加载服务。具体命令、预算、失败与续跑和验收见LLD §70.17；源证据保留在本轮单日报告中。

### 75.10 单日实测发现的恢复阶段错误修正

10月9日已登记，Raw run `23b6eeee-9189-44bb-a812-0951bc20a5c7`只提交一次，控制工具按方案正常退出130，后台任务继续。恢复时触发read_budget：旧实现仅按“已登记”决定从raw阶段开始，将接回观察错误记入已消耗的Raw提交预算，40次检查预算被提前用完。这是工具缺陷，不能以提高额度、清零记录或重发Raw处理。继续执行前先按LLD §70.18修正并复验，再以同一日期、同一root及原请求接回；旧清单和记录全部保留。

### 75.11 当前进度：10月9日单日验证完成，接续2/49

10月17日16:53独立只读验收通过：大盘10-09 Raw和Silver任务均SUCCESS，每层恰好1个任务、1条物化、1条准确绑定的通过检查，正式文件各1行15列；源端两轮共2请求、间隔60.196秒，字段转换及摘要正确，reject 0。停止工具没有取消后台Raw；恢复缺陷按§75.10修正后接回同一Raw并完成Silver，Raw检查预算保持40未清零。重复同一清单新增0登记、0任务、0源请求。修正后109项隔离测试通过，正式验证与测试证据分别记录。

当前已完成七表历史接入7804个数据集日期；本轮接续49个数据集日期中，只有大盘10-08、10-09两个完成，**2/49，剩47项/94个完整任务**。其中大盘剩10-12～16共5天；另外六表各剩10-08、09、12～16共7天。21个自动更新仍全部关闭，P4整体及P5未完成。本次没有阻塞中的资金流任务，没有修改共享周/月线、配置、API/CLI合同、子系统依赖或重载服务。

已完成[单日验收报告](../../reports/moneyflow_p4_continuation_market_20261009_acceptance_20261017.json)及[剩余47项只读执行清单](../../reports/moneyflow_p4_continuation_remaining_plan_20261017.json)，后者SHA256=5d3da048513b7d99cd0051280f42c83bd2451182a625b1c15b9fb784d677b252，尚未apply。本步到独立单日验收边界，下一执行范围为该47项清单，之后才是自动更新启用及P5真实日更；源代码/服务/日期事实若变化，按既有规则重新只读核对，不能将清单自动延期。

### 75.12 本轮执行：完成七表数据接续这一步

管理员本轮明确要求“提交修改，然后按照方案继续推进，完成整体的第一步，注意不要跑偏”。上轮相关修正已提交a7b2ec62、4d5c5ea22，当前无资金流任务遗漏的待提交代码。整体第一步按当前已给出的后续顺序解释为完成数据接续：原47项清单共94个完整job，日期范围保持10-08、09、12～16，大盘已完成两日不重跑；不包含21个自动更新启用及P5。

复用原CLI，不新增生产代码、入口或业务配置。按原顺序执行：大盘剩5天；THS行业、THS概念、DC板块、DC个股、THS个股、moneyflow各7天。为保证每个新表第一天有独立读回报告，使用原清单的同根子清单：大盘一次5天；另六表各先1天、验收后再6天，共固定13个执行段。所有段保留47项父清单和同一root，身份不变、范围只缩小，不逐日重复申请批准。通过后汇总49项两层真实交付并重放0新增，方可关闭本步。

旧代码证明中的一个period合同已因周/月线独立恢复开发改变；已读当前实现和导入调用方，新增恢复参数/函数仅由周/月线使用，不改变资金流。依§70.9刷新当前隔离Definitions和源码证据后生成同范围子清单，不把旧摘要当现状，也不等待无关开发或改动其代码。精确命令、预算、读写及恢复边界见LLD§70.20。

### 75.13 实际推进至39/49及启动失败（2026-10-17）

前十段已完成；第十一段已完成THS个股10-09、12、13，10-14 Raw成功，Silver任务656aa7d0-94c5-477e-a72e-452a48618d2c在队列启动时出现本地gRPC `Stream removed`。后台将其标FAILURE；随后迟到worker看到已结束状态而退出，未开始业务步骤。当前服务及21个停止状态均健康。10-14的Raw共5215行、来源证明及检查齐全，SHA256=d813d99b7739b622d358fb8cc58916c816b0c3371c93474c0bb079244e2e1fc9；Silver正式文件、候选目录、物化及实际检查评估均不存在。原失败事实保留，无重试。

当前七表接续39/49完成、10项未完成：THS个股10-14缺Silver，10-15/16两层未执行；moneyflow七日未执行。Raw已就绪40项、Silver39项，详见[部分验收](../../reports/moneyflow_p4_continuation_full_20261017/partial_acceptance_after_launch_failure.json)。原方案§70.7明确失败即停止并禁止自动加attempt/换run继续，因此没有跳过坏日期去执行后续9日，也不假称整体第一步完成。

### 75.14 只恢复这次启动前失败，再继续原清单

拟按LLD§70.21增加显式、一次性的启动前失败恢复：仅允许上面的THS个股10-14 Silver，保留原失败任务，调用Dagster原生完整任务重新执行并建立父子关联；下载不重采、不复用不存在的Silver候选、不补造成功事件。原工具须同步认识“一个已确认启动前失败＋一个明确恢复任务”，其他重复或失败仍拒绝。不是自动重试任何失败，也不新增调度或来源。

这是超出原“失败后停止”的新处理，已先完成代码/现场审计及LLD§70.21具体方案。管理员随后表示“刚才程序暂停更新了，现在可以继续推进了”，本轮承接该具体恢复方案继续实施；仅增加这一次Silver，不扩大日期、来源或自动重试范围。原47项的最大提交次数由94变95（94次成功交付＋保留的1次启动失败），Tushare请求预算不增加；21个自动更新仍关闭。先修复、正反回归和隔离集成，再仅补这一次Silver并读回；成功后接续原余下9日并完成49项总验收。新方案不得用于重采已绿Raw、掩盖失败或绕过原请求记录。
