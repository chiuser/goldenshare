# Dagster 历史初始化与旧分钟数据修复总账

更新时间：2026-09-05。性质：历史证据摘要，不是执行手册。

## 1. 当前边界

旧湖迁移适配器已在清退专项 M3/M4 删除（M4 提交 `68f97744`）；旧 Console frontend/backend 已在 M6 同轮删除，历史入口不可执行。
本账只解释正式 Lake 历史数据如何形成，不提供旧湖路径、旧命令、Kopia 或可复用的旧 spec/executor。
历史 Dagster 事件中的旧来源字符串只读保留，不作为当前摄取能力或依赖。

日常更新、正式 Silver/Gold 重建、runless event 工具和 prod 只读 Raw 恢复仍保留，见
[正式分钟设计](dagster-stk-mins-asset-design.html)、[清退 LLD](legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md) 和
[正式模板](../templates/dagster-dataset-onboarding-template.html)。不得根据历史输入恢复旧湖读取链。

物理数据与文档删除分开：本轮 M5 不删除物理数据。旧 backup、旧湖和恢复遗留物按清退 LLD §16 的代码用途分类，
执行前仍需用户确认精确对象。“文档已删”或“过去迁移成功”不等于物理数据可自行删除。
完整旧文档可从 Git 基线 `5f834b02` 查阅；本账不建立第二套历史目录。

## 2. 正式新湖历史初始化结果

以下数字来自清退前已记录的执行结果，不是 2026-09-05 的实时扫描。
原文中的 M2/M3/M5/M6 是各自数据集的历史阶段，与当前清退专项同名阶段无关。

| 数据集 | 当时来源与处理 | 已记录结果 / 后续维护边界 |
|---|---|---|
| `suspend_d` | 旧湖停复牌分区；日期转 Raw 字符串，全空 suspend_timing 显式转字符串 | Slice 2.0.3 单日验证通过；合法无记录日允许空文件，后续由正式来源维护 |
| `trade_calendar` | 旧日历 full；boolean is_open 转 0/1，日期转 Raw YYYYMMDD | Slice 2.0.4 验证通过，后续由正式来源维护 |
| `stock_basic` | 旧基础信息 full；保持当时 Raw 显式字段，日期在 Silver 标准化 | Slice 2.0.4 验证通过；不保留旧湖初始化分支 |
| `stock_daily` | 旧日线分区；Raw 保留 change，Silver 使用 change_amount | 2026-04 共 21 个交易日完成；当时 Raw/Silver blocking checks 通过，unexplained missing/extra 均 0 |
| `adj_factor` | 旧湖因子初始化，生成正式 Silver，分别补事件 | 见 §2.1；现行日常 Raw/Silver job 独立执行 |
| `stk_mins` | 当时 backup 的 clean_next，一次性初始化 | 五频各 4,209 个 Raw 文件，共 21,045 个；2009-01-05 至 2026-05-07；动态分区 4,209 个，各 Raw asset materialized 4,209 分区，7 个 Raw blocking checks 各 succeeded=4,209、failed=0 |
| `stock_identity_map` | 旧身份映射 full 初始化 | 6,089 行、1 个 runless materialization、9 个 blocking check events，当时全通过；日常由正式基础信息自映射和版本化 seed 维护 |

### 2.1 复权因子的历史规模

- 初次 Raw：4,215 个分区，2009-01-05 至 2026-05-15，14,959,706 行；同批注册 4,215 个动态分区。
- Raw 文件与事件分开：之后 8 个 Raw blocking checks 各 succeeded=4,215、failed=0。
- Silver：4,215 个分区，13,908,872 行，全量只读审计失败分区 0；之后 10 个 Silver checks 各 succeeded=4,215、failed=0。
- 再补齐 2026-05-18 至 2026-05-29 的 10 个交易日。当时最终核验：分区、Raw/Silver 文件与 materialization 都为 4,225 个；Raw 8 项和 Silver 10 项 checks 各 succeeded=4,225、failed=0。
- runless events 不产生对应 Runs 页面执行记录，也不触发当时的飞书 run-status 通知；不是日常 job 已重跑的证明。新事件补录仍须单独审批。

### 2.2 分钟初始化时的已知语义

当时 clean_next 中存在 low=0、vwap=0、停牌结构行全 0 和少量 OHLC 区间残留。初始化 Raw 保留当时来源事实，
Raw 检查拦空值、负值和空代码，更强价格治理留给后续 Silver。期间外挂盘掉挂载导致一次事件审计失败，
恢复后先核验文件、分区和样本事件再补录；不能据此承诺任意中断都自动恢复。

## 3. 旧分钟数据修复的必要证据

本节收敛旧文档的必要结果，不把旧 schema 或旧过滤范围作为当前 Raw/Silver 契约。

### 3.1 Raw 事故与 clean_next 重建

- 旧单股票补数曾错误替换全市场分区。记录确认恢复严重低行数分区 3,735 个：1min 为 3,508 个（2010-08-27 至 2025-02-14），5min 为 227 个（2010-08-27 至 2011-08-05）。旧反向恢复和单股票专项入口随后退役。
- 2026-05-12/13 clean_next 重建：21,045 个分区，Raw 4,576,238,458 行，保留 4,428,800,144 行，过滤 147,438,314 行。其中上市前 10,281,480、退市证券 137,156,532、非法量额 302。这是两次后续修复前的构建行数。
- 当时 clean_next 物理字段为 `ts_code,freq,trade_time,open,close,high,low,vol,amount,exchange,vwap`。目录虚拟 trade_date 不等于物理字段；历史 11 列结论不要求现行 Silver 补回 vwap。
- 初次完备性审计 14,583 个问题。完成下列两次修复后，2026-05-13 全量复审 21,045 个分区、issue_count=0。旧错误 schema clean 后来单独获准删除；不等于当前全湖实时无缺口。

### 3.2 2022 北交所 30min 修复（2026-05-13 执行）

范围 2022-07-15 至 2022-12-30，共 115 个交易日、161 个唯一代码、13,568 个日-代码组合。
用当时同日同股票 15min 重建受影响 30min：81,408 → 122,112 行（每组合 6 → 9 bar），
目标分区总计 4,934,172 → 4,974,876 行。未受影响股票保留，15min 只读，missing_vwap_rows=0。
修复后基础/完备性 scoped audit 均 115 分区、issue_count=0。

### 3.3 2024-10-30 多频污染修复（2026-05-13 执行）

旧数据把部分股票 1min 行混入 5/15/30/60min。只重建受影响股票，未改其他股票和 1min 源。

| 频度 | 受影响股票 | 旧错误行 → 新行 | 分区总行数：修复前 → 后 |
|---|---:|---|---|
| 5min | 253 | 68,563 → 12,397 | 316,944 → 260,778 |
| 15min | 254 | 68,834 → 4,318 | 155,007 → 90,491 |
| 30min | 254 | 68,834 → 2,286 | 114,446 → 47,898 |
| 60min | 254 | 68,834 → 1,270 | 94,179 → 26,615 |

当时 missing_vwap_rows 均 0；修复后四频基础/完备性 scoped audit 均 issue_count=0。
旧问题账本不自动代表修后状态，结果依据是目标文件直读与复审。

### 3.4 分钟与日线代码集合不能无条件要求相等

2026-05-30 审计覆盖 2014-01-02 至 2026-05-15，共 3,004 个交易日；五频与日线均不能逐日 strict equality。
1min clean_only 为 206,975 个日-代码，全部被当时停牌事实解释；daily_only 为 33,126，
其中北交所映射 23,423、更名映射 3,446、未命中映射 6,257。未映射部分当时未作最终定性，不算已修复。
保留结论是先区分停牌、身份映射和未解释差异，不以日线行数或代码集合直接否定分钟事实。
现行证券身份、停牌过滤和缺口判定以正式资产/checks 为准，不得重新读取旧 manifest。

## 4. 不迁移旧执行体系

其余旧分钟指标开发、MACD v2、clean 发布、队列、锁和 UI 文档退出工作树。
有效的请求预算、内存、候选校验、原子提升及实测对账合入正式模板 7A 和性能治理 §6.4。
当前公式、参数、baseline、状态及恢复门禁以 [正式 MACD/KDJ 方案](dagster-stk-mins-qfq-macd-kdj-indicators-plan.md)、
[R5 对账恢复 LLD](dagster-stk-mins-qfq-macd-kdj-reconciliation-recovery-r5-low-level-design.md) 和受保护金样本为准。
旧指标性能样本不作为当前硬阈值；旧 Console 命令、锁、备份和 checkpoint 实体不迁入正式主链。
