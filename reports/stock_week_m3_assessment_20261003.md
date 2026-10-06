# DG 股票周线 M3 开发验收

2026-10-07纠偏说明：本报告保留历史结论；搬运/审计中间数据文件已按管理员要求清理，不再是正式检查或调度依赖。现行口径为 bootstrap 完整对账一次即结束、日常只检查当前新增周期。详见[清理记录](stock_period_reports_cleanup_20261003.md#2026-10-07运行依赖纠偏及清理)。

日期：2026-10-03，Asia/Shanghai。M2已按管理员指令提交`30b118ff`，未推送。M3年度候选、源对账和单文件提升恢复已完成开发及私有临时目录验收；M3修改尚未提交。正式Lake、正式staging、Prod和Dagster instance均未写入。

## 目标、依据与改动

依据[原方案](../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)、[LLD §7–8及§22–23](../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)、DG dataset onboarding模板§7A、性能治理规范和当前M1/M2合同。保留三源原始业务字段、日期和单位，不增加复权计算或清洗。

| 文件 | 实现／验收 |
|---|---|
| `defs/io/stock_weekly_raw.py` | 显式schema、年度relation、NULL-safe集合合并、同值去重、异值阻断、canonical hash、一次PARTITION_BY及双向EXCEPT ALL读回 |
| `defs/bootstrap/stock_weekly_candidates.py` | frozen capture receipt、外部文件hash、跨自然年输入、existing-only保留、目标baseline、年度audit签名、备用expected-key外部台账 |
| `defs/bootstrap/stock_weekly_promote.py` | 全文件预检、source/week全局OS锁、跨设备阻断、逐文件promoting/verified checkpoint、replace/fsync、实际目标读回、退出恢复 |
| `defs/bootstrap/stock_weekly_capture.py` | 只追加validated_receipt；复用当前验证，不更新checkpoint，不改resume |
| `tests/test_stock_weekly_candidates.py` | 24项三源、跨年、NULL、冲突、证据篡改、路径、并发、预算、取消及真实进程退出测试 |

原方案、LLD、docs索引同步更新；本报告及测量JSON（历史中间文件已清理）保存验收。没有改变共享resource、API/CLI、DatasetDefinition、活跃资产/catalog/sensor或业务子系统依赖矩阵。

## 硬口径对账

- 每来源/锚点年度统一构建，输入为全部相交的已封存unit。缺receipt拒绝；主源完整年度模式缺邻年库存拒绝。2020-12-31与2021-01-01合并进入2021-01-01周，源日期原样保留。测试直接验证两行均存在。
- 主源13/21列、备用11列来自单一合同；Hive week_end不写入Parquet。49行含业务NULL的主源样本保留；备用4行非周五样本保留。异常OHLC、主源负vol/amount只计观察；备用负vol/amount阻断候选。没有单位换算。
- existing-only全部保留，同键同值仅一行，同键NULL/非NULL或异值阻断。目标重复key、坏schema、错误周和额外part阻断。source/owned/boundary/excluded/duplicate及candidate=existing+new_keys计数留存。
- 候选全年度双向EXCEPT ALL为零；物理schema、业务key、每周归属、行数、canonical及文件hash全部校验后才封存audit。签名分别绑定manifest、候选清单、target baselines、schema及来源证据。
- 备用expected库存为CSV/Parquet，必需ts_code、week_key；按每个frozen unit核对selected-key逻辑hash/count。外部台账记录source_key_present/source_key_absent_confirmed，先验证完整成功receipt才允许记录缺行。技术失败/缺证据不会转为已查空。该台账只覆盖已批准请求候选，不能代替全市场日线期望、身份等价或复权完整性审计。
- apply=False仅做预检，不创建目标或writer locks。apply先核验所有文件、同卷及source hashes，再持全阶段周锁逐文件复查baseline；单文件replace是持久化边界，不宣称整年度组级原子。已完成文件不因后续取消回滚。
- replace前后各有真实spawn子进程以exit23退出的测试。OS锁随进程释放；候选被搬走后用promoting checkpoint及目标hash恢复，读回后verified。重复执行、取消一周后续跑、并发持锁及跨设备阻断均覆盖。

## 性能与真实样本

只消费M0真实源值及M2已验证捕获，源调用0，无生产网络传输。当前正式路径没有作为测试资源。一次源读取/年度合并/年度COPY/年度全集读回，扫描次数不随52周线性重复；最终提升只读回对应单周。遵守512MiB/2线程/2GiB spill额度、1200万source+existing行、10000代码、3000文件、每周max_codes×7行上限；超限拒绝，不截断。

| 来源 | 源行／候选行 | 周文件 | 构建／提升（秒） | 重建新增key |
|---|---|---|---|---|
| 主源未复权 | 15346／15346 | 52 | 0.1984／0.2738 | 0 |
| 主源复权 | 15346／15346 | 52 | 0.2467／0.3438 | 0 |
| 备用weekly | 51／51 | 51 | 0.0855／0.2551 | 未测二次构建；已测checkpoint幂等 |

累计进程峰值RSS435.219MiB，spill未触发。DuckDB内存额度不等于整进程RSS上限；没有证明1200万行或强制spill的耗时。COPY分区参数参考[DuckDB官方文档](https://duckdb.org/docs/lts/sql/statements/copy)，实现能力以本机现有版本执行结果为准。

主源样本只有自然年2025库存，显式partial_scope，不能宣称跨边界完整历史。partial_scope只供隔离临时目标，正式Lake禁止该模式。正式bootstrap需要完整邻年库存与真实captured/成功空证据；最早/最晚历史边界无邻年数据时，M5冻结范围应显式提供可验证的空窗口证据，不能伪造非零inventory或放宽门禁。本轮跨年逻辑用完整三年隔离inventory验证。

备用样本冻结候选2键，2键均在51行源响应中；保留请求区间的全部51行，不把只批准两个缺口键误作只保留两行。另有正反测试证明一键存在、一键成功请求后缺行，以及expected逻辑hash不符拒绝。

## 验证与影响面

orchestrator现有.venv：

```bash
.venv/bin/pytest -q tests/test_stock_weekly_candidates.py tests/test_stock_weekly_capture.py tests/test_stock_weekly_history.py tests/test_stock_weekly_source.py tests/test_stock_weekly_prod_source.py tests/test_stock_weekly_contract.py tests/test_stock_weekly_planner.py tests/test_run_contract_static_gates.py tests/test_etf_mins_prod_db.py tests/test_index_mins_prod_db.py
```

224 passed，4条既有Pydantic警告。最终仅追加NULL/OHLC观察计数后，M3定向24项再次通过，真实样本重新测量并刷新JSON。五个Python文件默认Ruff及全项目致命错误基线通过；文档完整性和diff检查通过。未修改通用DuckDB连接工厂或OS隔离runner；M2已完成的27项受保护DuckDB回归仍作为该未变helper的上一阶段证据，不声称本轮重跑。

开发前CodeGraph explore/impact核验M2 capture、paths、DuckDB连接及resume调用方；开发后sync/status、query promote_weekly_candidates、impact WeeklyCaptureStore/validated_receipt核验新增调用链。直接imports审计确认：新入口只由本切片模块和测试引用，没有活跃Dagster、Prod DatasetDefinition/TaskRun或前端消费者。CodeGraph索引结果不替代正式运行验收。

初次测试发现重复fixture在M2 receipt阶段已经被合法阻断，改为在年度relation层验证合并规则，未放宽capture验证。两次命令因工作目录/文件名不符未运行，纠正后执行上述实际通过的命令；没有安装套件或绕过受保护测试。

## 下一阶段

M3开发及隔离验收完成。下一步M4接入definitions/catalog/schema/分区/check与受限配置消费者。正式bootstrap、生产传输验收、全历史覆盖与身份分类、runless events及更新机制仍按后续里程碑，不能据本报告宣称周线已正式接入或缺口已清零。
