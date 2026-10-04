# 月线 M10.C 隔离开发验收

2026-10-05，Asia/Shanghai。M10.C bootstrap helper开发完成；未写正式Lake、注册分区、触发job、补录事件或启用sensor。前序周线与月线M10.B已提交 `981fb1cc`，本轮M10.C改动尚未提交、未推送。

已实现两源Prod只读业务字段SQL与监督导出、冻结计划重算/库存hash、成功unit receipt、Decimal/NULL保真、年度库存对照、20200229排除台账、全候选差集校验、跨计划/IO配置共用月文件锁、目标fingerprint、同值复用/异值停止、同卷逐文件os.replace和checkpoint续跑。没有修改weekly helper、正式definitions、Prod API或src分层。

| 保存的真实Prod样本 | 捕获 | 排除29日 | 候选/提升 | 临时文件 | 全字段差异 | 全链路含重放秒数 |
|---|---:|---:|---:|---:|---:|---:|
| primary_unadjusted | 3854 | 293 | 3561 | 12 | 0 | 0.9429 |
| primary_adjusted | 3860 | 295 | 3565 | 12 | 0 | 0.8946 |

样本来自M10.B已导出的2020年度、各300代码；本轮未重新查询Prod。旧样本CSV的空NULL先用DuckDB转换为新transport的明确\N编码，仅转换传输表示；监督器只读snapshot控制证据为隔离替身，不能声称新的真实Prod事务已验收。两源2月正式候选只含20200228；29日所有业务列留在staging排除Parquet。每源全链路及receipt重放只进行一次本地样本导出。RSS是整个进程累计峰值，最高351.859MiB；结束spill=0，未测峰值或强制spill。样本不能证明全量覆盖和全量性能。

月线111项、与相邻周线合计181项回归通过；受保护静态113项、资产治理12项通过，Ruff及全src/tests致命错误基线通过；整个code location离线隔离dg check defs加载成功。测试覆盖真实子进程成功/坏控制、取消/超时/字节上限、receipt封存后进程退出、提升后checkpoint之前中断、checkpoint失败不回滚文件、续跑、双源Decimal、缺28不取29、重复键、错列/频度/日期/范围、候选篡改、库存漂移、target变化、锁冲突、跨文件系统与低磁盘拒绝。

唯一复用基础能力为统一DuckDB连接入口；新模块不依赖Dagster instance、src/ops或旧湖。CodeGraph已分析既有capture/candidate/IO与连接入口影响面，根索引sync；修改的纯monthly plan仅现有planner/测试和新增bootstrap消费者，不改变外部API。

配置集中在MonthlyBootstrapIOPolicy且进入执行目录/receipt/audit身份；既有StockMonthlyPolicy仍负责范围与行数。计划保留范围与年度库存，可重算验证；M10.B旧JSON只是历史规划证据，本轮不新增兼容读入器。正式读取量沿450 units/402 files/1,414,335 accepted rows设计，按unit与年度分批；正式sample前必须刷新库存及磁盘预检。

下一步M10.D：注册两套月线assets/checks/catalog/paths/partitions并集成手动、每天19:30自动更新及月份完成证据。M10.E正式文件/事件执行、M10.F更新验收另列；M9仍待周线源版本可交付后正式验收。无需新增业务拍板，不能将本轮隔离测试作为正式写入或启用授权。

证据：[样本报告](stock_month_m10c_sample_20261005.json)、[代码/验证记录](stock_month_m10c_validation_20261005.json)、[LLD](../lake_console/docs/design/dagster-stock-monthly-raw-onboarding-low-level-design-v1.md)。
