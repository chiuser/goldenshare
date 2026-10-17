# DG周/月Silver生成与验收（2026-10-17）

**结论：首次Silver生成及正式验收通过。** 周线656文件/2,510,076行；月线154文件/595,608行；合计810文件/3,105,684行。实际810条物化、2,430条blocking检查全部通过，均绑定正确资产、分区和物化ID。正式补报run为SUCCESS。

## 目标与范围

依据原总方案§7.3/7.4、共享LLD §9/§10、月线LLD §6/§7实施；复用已通过的`dg_stock_period_silver_readiness_20261017_135833`审计。只生成两套Silver、可复用单周期job和六项检查；Raw 21列列名、顺序、类型、值、单位与NULL不变，源YYYYMMDD日期保留VARCHAR，change不改名，三套价格均未重算。未重新审计完整性或请求源站。

| 资产 | 已落盘范围 | 文件 | 行数 |
| --- | --- | ---: | ---: |
| silver_stock_weekly | week_end=2014-01-03—2026-10-16 | 656 | 2,510,076 |
| silver_stock_monthly | month=2014-01—2026-10 | 154 | 595,608 |

两根分别为`/Volumes/datasource/data_lake/silver/quote/stock_weekly`和`stock_monthly`，每期一个part-000.parquet。月线2026-10源标签20261031合法，计算截止20261016；不冒记整月完成。上市首周/月和20140103跨年首周整根保留，整期上市前记录排除；审计中的7个边界周线未被二次停牌过滤删除。同股同周期取最大源end_date整行，最新同版本异值拒绝，未合并价格或改写日期。

## 逐条对账

| 已确认要求 | 实现位置（相对orchestrator） | 正反验收与结果 |
| --- | --- | --- |
| 21列原样继承 | run_contracts/stock_period_silver.py；asset_column_schemas.py；stock_period_silver.select_period/validate_projection | 独立字面schema/NULL/Decimal及真实缓存样本；DATE、DOUBLE、改名、额外列、改价/NULL/代码、缺行/重复行均拒绝；810次整行双向EXCEPT ALL通过 |
| 范围、完整首期与最新版本 | make_execution/select_period | 跨年首周、上市首周/月、当前未结束月正测；完全上市前/退市对象排除；错身份/日期/频率/分区/越界审计拒绝；20200229最新整行保留，旧20200228不顶替；并列异值拒绝 |
| 独立Silver路径和唯一写者 | paths.py；io/stock_period_silver.py | 未知目标和符号链接拒绝、真实独占锁冲突拒绝；正式开工两根不存在、同设备、约2.9TB free、无相关写者；无清根或备份 |
| 每周期一次处理 | stock_period_silver.build | 一个进程/连接，参考表只加载一次；真实缓存单期各一次Raw全读/COPY/完整候选读回及一次footer；完成续跑零SQL、版本不变；正式810文件累计验收，不重读全湖 |
| 取消与续跑 | cancellation/build/publish | 实际TERM/KILL退出、SQL中断、取消后不领新unit、候选保留、锁释放；validated候选复用；rename成功但checkpoint失败可补记；源/参考/候选漂移与伪造执行身份拒绝 |
| 文件和事件分离 | bootstrap/stock_period_silver_cli.py | 事件写失败不改文件，恢复只补事件；真实隔离Dagster存储证明无重复；伪run/PLANNED/失败/非blocking/错分区或物化不能顶替；正式实际810+2430条事件绑定通过 |
| asset/job/check/catalog及中文名称 | assets/jobs/stock_weekly.py、stock_monthly.py；checks/stock_period_silver_checks.py；catalog/lake_assets.py、name_mapping.py | 真实单周期job只选Silver及其3项check，不触发Raw；临时完整definitions验证通过；正式加载两asset/两job/六blocking定义；两名称补项已获批准 |
| 边界、消费者与文档 | 原三文档、两份直接治理测试 | CodeGraph explore及sync/status完成；Raw函数/装饰器AST与HEAD一致；移除本次新增节点后catalog AST与HEAD一致，保留其他任务格式；R3源码hash开工/收尾相同，Raw sensor状态和业务水位相同；无Silver sensor/Prod/API变更 |

完整机器证据见[final_result.json](final_result.json)、[formal_commands.md](formal_commands.md)、[change_boundary.json](change_boundary.json)。逐文件验证和事件checkpoint保留于`/Volumes/datasource/data_lake_staging/stock_period_silver/run_id=d895bec0-8b69-4cd3-aabe-7f06a4c7e467/`。

## 测试与证据边界

新增Silver的43项隔离测试全部通过；包括真实临时Parquet、SQL、CLI、进程退出、Dagster job/check和事件存储。字面夹具依据现行Raw schema及真实生命周期/身份合同；expected独立于待测selector。此前真实Tushare样本只复制两个缓存Raw文件到临时根，走本次最终生成器，未重新请求或使用正式资源作测试。周线20140103与月线20200229/close_qfq=11.1400均与独立预期一致。[cached_sample.json](cached_sample.json)保存SQL和成本。

扩展直接回归73项通过、2项未通过（不计作通过）：全局治理表既有15个其他数据集缺项，已用HEAD版本确认不是本次引入；另一个停牌外部资产用例需要其专用启动器，直接pytest时缺少stock_suspend_confirmed_test_support。本次没有修改这些未通过项的断言、使用skip或扩大修复范围；两新资产的治理登记及metadata消费者均通过，完整错误保留[final_tests.log](final_tests.log)及[final.xml](final.xml)。不据此声称全仓回归通过。Ruff致命错误基线及所有本次Python改动默认规则通过，完整definitions在隔离instance验证成功。

## 正式实测

| 项目 | 实测 |
| --- | ---: |
| 文件阶段 | 31.889秒 |
| 源整行选择累计 | 14.776秒 |
| COPY累计 | 3.813秒 |
| 完整候选校验累计（含该阶段fsync） | 10.997秒 |
| 提升/目录fsync/footer累计 | 0.994秒，不含随后checkpoint写入 |
| 独立正式文件进程峰值RSS | 896,434,176字节，约855MiB |
| 实际输出 | 170,035,374字节，约162.2MiB |
| 事件补报阶段 | 110.642秒，单个真实Dagster run |
| 源请求、最终再次全量Parquet扫描 | 0、0 |
| 最终残留spill文件 | 0（不冒充瞬时spill峰值） |

复用既有DuckDB 16GB/4线程/512GB引擎上限，只指定本run spill；上限不是实际占用。以上为本次正式实测，不用小样本推算全市场。最后仅汇总已生成证据、一次目录元数据清单及8个批量事件查询，不重新按证券/日期/分区跑完备性审计或readiness。

## 当前交付状态

设计、代码、隔离验收、正式文件、DG登记均完成。原三份生成设计已先提交ace57334b；本次实现、补项和收尾文档仍为工作区改动，未推送。其他任务未提交改动保留。后续日常自动接线仍需另行明确，应消费Raw实际变更的全部周/月；本次没有新建或启停Silver sensor。Prod和R3继续后置，本次没有推进。
