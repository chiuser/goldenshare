# Goldenshare Dagster 数据湖工程

2026-09-05 清退 M6：旧 Console frontend/backend、Kopia、旧专属测试、启动入口和示例配置已同轮删除。
目录名称保留，不代表旧管理台仍可启动。历史代码可从 Git 查阅，不提供兼容入口。

## 现在保留什么

| 目录或入口 | 当前职责 |
|---|---|
| [orchestrator](orchestrator/README.md) | 正式 Dagster assets、checks、jobs、sensors、catalog、离线维护 CLI |
| [docs](../docs/README.md) | 正式设计、接入模板、初始化与修复证据 |
| `reports/` | 仍被引用的审计与研究报告，本轮不删除 |
| [lake-clickhouse-start](bin/lake-clickhouse-start) | 本机 ClickHouse 启动工具；执行会改变服务状态 |
| [lake-prod-clickhouse-tunnel](bin/lake-prod-clickhouse-tunnel) | 生产 ClickHouse SSH 隧道工具；执行会建立连接 |

正式 Lake 根是 `/Volumes/datasource/data_lake`，仅有 raw、silver、gold 三层；
候选文件和运行 staging 位于 `/Volumes/datasource/data_lake_staging`。
事实以 [paths.py](orchestrator/src/orchestrator/defs/paths.py) 和当前 catalog 为准。
ignored 的 `config.local.toml` 属于旧产品遗留配置，不能决定正式根。

## 开发与维护入口

- [目录规则](AGENTS.md)、[编排工程规则](orchestrator/AGENTS.md)
- [正式数据集接入模板](docs/templates/dagster-dataset-onboarding-template.html)
- [数据管道性能治理](docs/design/dagster-data-pipeline-performance-governance.md)
- [初始化与修复总账](docs/design/dagster-bootstrap-legacy-links.md)
- [清退专项 LLD](docs/design/legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md)

现行分钟历史维护使用 orchestrator 的 Silver、QFQ、derived、MACD/KDJ 四个 CLI，共 21 个命令。
单日五频 Raw 恢复使用独立的 `stk_mins_raw_replace_from_prod_cli.py`。
这些都是人工维护入口；参数、确认条件和运行授权以各自方案及当前 CLI 为准，不能用旧 Console 命令替代。

## 保留边界

正式 orchestrator、本机／生产 ClickHouse、Foundation Lake Reader 和 Wealth 分钟 API 继续使用。
生产 Ops 的 `ops.dataset_status_snapshot` 与 Kopia 备份不是一回事，不属于清退对象。
本轮不修改资产字段、路径、21 CLI 的行为，不操作数据库或正式 Dagster。

本机 ignored 环境、依赖、构建产物和配置仍保留；物理旧湖及恢复遗留数据不随代码目录删除。
后续物理清理必须按当前代码用途结论给出精确清单，并由管理员确认。
现行停牌修正规则 CSV 仍由代码读取，必须保留；取消这项隐性文件依赖的 TODO 见清退审计清单。
