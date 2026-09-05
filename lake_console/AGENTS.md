# AGENTS.md — Dagster 数据湖工程规则

## 适用范围与当前结构

适用于 `lake_console/` 及子目录；更近规则优先。2026-09-05 M6 已删除旧 Console
frontend/backend、Kopia、专属测试、旧入口和示例配置，不得恢复旧产品或兼容入口。
当前保留 orchestrator、正式 docs、reports 和两项 ClickHouse 工具。

## 动手前必读

1. 仓库根 AGENTS.md，以及本机存在时的 AGENTS.local.md。
2. `lake_console/orchestrator/AGENTS.md`、更近规则、当前实现与已批准方案。
3. 清退任务遵守专项方案、LLD 和 M0 审计清单。
4. 管道、数据集、readiness、sensor、check、bootstrap、runless event、DuckDB/Parquet
   任务必须读 `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`。
5. 接入使用 `lake_console/docs/templates/dagster-dataset-onboarding-template.html`（含 7A）；
   源请求按根规则读本地源文档并真实验证，不能凭印象编码。

## 工程与生产边界

1. 本工程独立于生产 Ops 和 Web；不得 import src/ops、生产 src/app 入口或 frontend/src，
   不挂入生产 Web／Ops 路由，不接入生产 scheduler/worker，不修改生产部署脚本来启动本工程。
2. 不把生产 API 的时间语义、股票池和默认值直接套到 Lake；先审计当前实现、源契约与文件消费者。
3. 生产数据库访问只能由具体数据集已批准的 resource、字段投影与过滤白名单承载，默认无权访问。
   只读来源与已另行批准的 serving 发布写入分开，不可互借权限。
4. prod-raw-db 只读导出限 raw_tushare 白名单表；prod-core-db 原有指数白名单限
   core_serving.index_daily_serving、index_weekly_serving、index_monthly_serving。
   新增来源先做专项审计，不因清退而放宽。禁止 select *；不带入 api_name、fetched_at、
   raw_payload、source、created_at、updated_at 等内部系统字段；必要映射须写入合同。
5. stock_mins 日常 Prod 完成门禁的窄例外保留：仅通过
   `ProdPostgresResource.connect_readonly_transaction()` 读取 ops.task_run 的 id、
   任务身份、状态、结束时间、完成单元、结果计数和 time_input_json/filters_json 明确字段；
   仅对 raw_tushare.stk_mins 按日、频度和预期代码集合查询 freq/ts_code/trade_time 的存在性覆盖。
   该门禁不能读其它 Ops 表、OHLC、成交量或 payload，不能写远程库。
   这是 readiness 限制，不是禁止已批准的 Raw 恢复读取行情字段。
6. 除上述窄例外外，不使用生产 task_run、schedule、dataset_status_snapshot、
   dataset_layer_snapshot_current 补充 Lake 文件或运行事实。
   生产系统自身的 Ops snapshot 继续保留，不属于 Kopia 清退。
7. 主要指数名单使用 `orchestrator/src/orchestrator/seeds/market/major_indices.cn_a.csv`；
   不恢复旧 Console 的 Ops active-pool → manifest 路径。
8. 本机和生产 ClickHouse 是不同 resource／连接配置；保留当前已批准消费者，
   不把旧后台清退扩大为 ClickHouse 清退或新增写权限。

## 文件与写入安全

1. 正式根只允许 `/Volumes/datasource/data_lake/raw|silver|gold`；
   候选与运行 staging 只允许 `/Volumes/datasource/data_lake_staging`。
   以正式 paths.py 为准，不读旧 config.local.toml 或 GOLDENSHARE_LAKE_ROOT 兜底。
2. 禁止将旧湖作为正式根、读取事实源、bootstrap 输入或 staging；旧迁移适配器已清退。
   不把“目录尚在”解释为仍允许业务读取。
3. 禁止任何 Kopia 命令、备份、快照及旧服务复用。写入使用候选完整校验、
   同文件系统逐文件原子提升、checkpoint 和物理对账；不能声称多文件整体原子性。
4. 写入前检查挂载、读写权限、剩余空间、目标冲突及人工维护窗口。禁止直接覆盖正式文件；
   未获明确批准不得创建移动盘目录、复制大文件、重写历史或写入正式 Dagster event。
5. 正式 DG 按生产环境对待。测试使用临时文件、替身和隔离 instance，不得用正式资源试跑。
6. 物理数据与 ignored 环境、配置、构建产物不随 Git 源码删除。
   清理需按代码直接引用和当前用途给出精确清单，经管理员确认后执行。
7. reports 不是旧后台专属目录，不可整目录删除。
   `orchestrator/src/orchestrator/defs/corrections/suspend_full_day_ranges.csv` 仍有现行读取，
   必须保留；取消文件式隐性依赖的 TODO 单独推进。

## 性能与开发门禁

1. 编码前列对象、日期、分区、枚举、请求、分页、行数、文件数、scan/join/write、spill、
   临时目录、commit/replace 粒度、耗时、空间、配额、拒绝阈值和验证方式。
   没有上界或样本、超过阈值时先改方案，不能先全量试跑。
2. 大体量文件计算使用 DuckDB SQL／COPY 或等价列式能力；Python 只做编排、校验、
   路径发现、批次规划、少量样本与汇总，不做大规模逐行处理。
3. 全市场、跨多年、分钟历史、bootstrap、runless event、数据库导出先做 dry-run、小样本或聚合审计。
   历史 readiness 优先集合差异与聚合计数；分区数超过 100 或
   partition_count × blocking_check_count 超过 1000 时不得全量逐分区深扫。
4. 生产只读导出先明确表、字段、过滤、分批、单批上限和预计行数，禁止无边界探测。
   full snapshot／共享资产需说明唯一 writer、重复触发及并发保护。
5. 长任务持续输出与已完成工作一致的阶段、对象、完成量和耗时，不能仅结束时输出总数。
6. 定义放 orchestrator/defs；源可用性探测按数据集放 source_readiness；
   sensor 只编排，不写 Parquet；resource 只封装外部能力，不放数据集逻辑。
   文件名体现职责和数据集；不新增宽泛 utils/types 文件，不夹带历史 helper 搬家。
7. 每轮只有一个批准目标。跨边界改动先做 CodeGraph 与全消费者审计；
   测试含正向与禁止项，修改既有方案同步原文。

## 验证与交付

运行本轮最小回归；文档变更执行 `python3 scripts/check_docs_integrity.py`。
清退护栏为 `tests/architecture/test_lake_console_retirement_guardrails.py`，
只检查 Git 源码和新非 ignored 文件，不把本机依赖环境误判为残留源码。
说明目标、依据、改动文件、边界影响、实际验证、性能测算、是否操作正式资源、风险与下一步。
