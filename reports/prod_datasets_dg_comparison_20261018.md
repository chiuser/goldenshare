# Prod与DG数据集差异更新（2026-10-18）

核验结束时间：2026-10-18T09:18:14+08:00。原文件仍在，已将[原差异CSV](prod_datasets_missing_in_dg_20261002.csv)更新为当前结果；保留20261002文件名供已有引用使用，实际核验时间以CSV列和本文为准。原74项版本可从Git追溯，本次更新前SHA256为`7b741de0ee396b88ef159be55fcbbef1b0a0f4c1b961aeacba8700aad8c439be`。

## 当前结果

| 统计项 | 数量 |
| --- | ---: |
| 当前工作区DatasetDefinition | 94 |
| 按数据集和来源拆分 | 95 |
| Prod实测有数据的来源项 | 95 |
| DG已接入且有非空Raw文件的来源项 | 30 |
| Prod有数据、DG仍缺对应来源的项 | 65 |
| 其中Tushare / BIYING | 62 / 3 |

若每个DatasetDefinition只取默认来源，则是94项中30项已接入、64项未接入。`stock_basic`同时定义BIYING和Tushare来源，本次分别统计，故来源项总数为95。旧差异表未列`stock_basic / biying`；本次补列，并非新增了一个DatasetDefinition。

[完整95项对照表](prod_datasets_dg_comparison_20261018.csv)保留全部结果和DG非空文件样本；[核验证据](prod_datasets_dg_comparison_20261018.json)保留实际SQL、179条Prod存在性结果、50个DG文件页脚结果、当前定义清单和代码摘要。主差异CSV仅保留65个尚有差异的来源项，不把已接入项继续混在缺口中。

## 相比旧74项，移除的10项

这些项目均已核对当前可加载资产及正式非空文件，不能再写“尚未接入”。

| 数据集 | 名称 | 来源 |
| --- | --- | --- |
| `anns_d` | 上市公司公告 | tushare |
| `moneyflow` | 个股资金流向 | tushare |
| `moneyflow_cnt_ths` | 概念板块资金流向(THS) | tushare |
| `moneyflow_dc` | 个股资金流向(DC) | tushare |
| `moneyflow_ind_dc` | 板块资金流向(DC) | tushare |
| `moneyflow_ind_ths` | 行业资金流向(THS) | tushare |
| `moneyflow_mkt_dc` | 市场资金流向(DC) | tushare |
| `moneyflow_ths` | 个股资金流向(THS) | tushare |
| `stk_period_bar_adj_month` | 股票月线行情（复权） | tushare |
| `stk_period_bar_adj_week` | 股票周线行情（复权） | tushare |

旧74项 − 本次确认已接入10项 + 旧表遗漏的BIYING股票基础信息1项 = 当前65项。

## 需要避免的误解

- **股票普通周/月线仍列原接口差异。** `stk_period_bar_week`、`stk_period_bar_month`对应Prod的`stk_weekly_monthly`；当前DG的复权周/月Raw及`silver_stock_weekly`、`silver_stock_monthly`来自`stk_week_month_adj`，21列含未复权、前复权和后复权价格。本次也核对两份Silver非空文件。因此这两项表示原接口未接入，不能解释为DG没有周/月线或没有未复权价格。
- **BIYING来源单独看。** 仍缺`biying_equity_daily`、`biying_moneyflow`、`stock_basic / biying`三项。Tushare同类资产不能抵消BIYING差异；共用serving表不能单独证明某个来源有数据，已用各来源Raw或std的source_key条件核对。
- **公告当前是Raw接入。** `anns_d`已接入且非空；不因此声称有独立公告Silver。
- **有非空文件不等于完整。** 本次不判断日期/对象覆盖、最新日期、逐字段等价、check成功或自动更新是否正常。DG周/月对象范围和Prod可能不同，不能将“接入”升级为“数据完全一致”。资金流待3个真实交易日的验收安排仍见原资金流方案§79/LLD§74，不因本表更新而关闭。
- **DG额外数据不拿来凑Prod数量。** 180个资产含派生层、多个频度及发布层，不能与94个Prod定义直接相减；`index_global`、`major_index_mins`不在当前94定义内，未新增成Prod缺口或从其他项目中抵扣。
- **已知定义差异仍存在。** `biying_equity_daily`的raw_table声明`raw_biying.equity_daily`在Prod不存在，真实target_table为`raw_biying.equity_daily_bar`且有数据；本次仅如实备注，没有修改代码。

## 65个来源差异项的分布

| 数据域 | 数量 |
| --- | ---: |
| 低频数据 | 7 |
| 公募基金 | 7 |
| 基础主数据 | 7 |
| 指数 / ETF | 8 |
| 新闻资讯 | 5 |
| 板块 / 题材 | 10 |
| 股票行情 | 20 |
| 资金流向 | 1 |

## 本次核验范围与成本

1. 当前代码依据为`src/foundation/datasets/registry.py`及其94个定义；DG以当前catalog和隔离加载的Definitions核对，180个资产可加载。没有用历史方案代替代码，没有连接/加载正式DG服务。catalog有其他任务既有未提交的格式改动，未修改其内容，证据保存本次实际代码摘要；也未声称Prod部署代码恰好等于本地代码。
2. Prod唯一入口为`bash scripts/psql-remote.sh`，目标为`.env.web.local`所指正式PostgreSQL。白名单为94个定义的raw/std/serving/target表及已审计的`raw_biying.stock_basic`，共171个表/视图名，分布于raw_tushare、raw_biying、core、core_multi、core_serving和core_serving_light。先读取4061条表结构元数据，确认170个存在、1个声明表不存在；再按身份及来源返回179条EXISTS布尔结果，业务明细返回0行。
3. 元数据查询事务READ ONLY，10秒语句超时；存在性查询单个REPEATABLE READ/READ ONLY事务，30秒语句超时；均2秒锁等待上限，最终ROLLBACK。每个存在性子查询SELECT 1/LIMIT 1；周/月严格使用freq=week/month，std来源表按source_key过滤。没有count全表、导出明细、请求Tushare/BIYING或改写数据。
4. DG唯一正式根为`/Volumes/datasource/data_lake`。按当前48个Raw资产及两个周/月Silver的精确路径模板查找，每资产最多20个候选、找到非空即停止；实际读取50份Parquet页脚num_rows，约0.580秒，业务数据页读取0。没有读取退役Lake、staging全目录或历史全量明细；无sensor、job、check、runless event、分区或游标操作。
5. 隔离加载时禁止网络、正式Lake/instance路径和.env读取，不启动instance或任务；报告生成只改reports下本文、两个CSV及JSON证据。无业务代码、配置、依赖矩阵或数据修改，也未提交或推送。

## 后续使用

本表用于选接入对象；实际接入前仍须按该数据集方案/LLD核对源合同、读取范围和性能。普通周/月线两项先确认业务已有字段是否已满足需要，不因“原接口未接入”重复做一条相同业务链。本轮没有执行任何新接入开发或数据补齐。

本轮结果文件验证：两个CSV分别65/95项且身份不重复，差异集合与完整对照表一致，旧74项与本次增减逐项对账通过；180个catalog资产与隔离Definitions完全一致，179条Prod布尔结果和50个页脚记录齐备，代码摘要复核不变。CSV统一使用LF换行以通过Git空白检查；CSV字段和值不受影响。文档完整性与本报告链接检查通过。
