# 本机 DG 常用操作命令

更新时间：2026-09-16。适用于当前机器和现有虚拟环境，不安装或升级软件。

## 1. 开机后启动本机 ClickHouse

在终端执行：

```bash
bash /Users/congming/github/goldenshare/lake_console/bin/lake-clickhouse-start
```

**例子：**电脑刚开机，本机ClickHouse还没启动，直接执行上面这条命令，不需要改参数。正常启动会显示 `ClickHouse is ready.`；如果原本已经启动，会显示 `ClickHouse is already running.`。这是启动服务的操作，不会替你触发DG同步。

脚本会检查本机 HTTP 8123 和 native 9000 端口；已就绪则直接返回，否则后台启动现有 ClickHouse，最多等待30秒并输出诊断。无需使用 `brew services start clickhouse`，本机采用独立二进制部署。

单独检查本机服务：

```bash
/Users/congming/.goldenshare/clickhouse/bin/clickhouse client \
  --host 127.0.0.1 --port 9000 --query 'SELECT 1'
```

**例子：**刚执行完启动命令，想确认服务能查询，就执行这一条。正常输出如下；这是只读查询：

```text
1
```

返回 `1` 表示这个本机连接可用，不代表 prod ClickHouse 可连接。

### 访问 prod ClickHouse 还要开隧道

另开一个终端，执行并保持终端运行：

```bash
bash /Users/congming/github/goldenshare/lake_console/bin/lake-prod-clickhouse-tunnel
```

**例子：**本机审计已经成功，但prod两个ClickHouse资产报19000端口连接失败，就在另一个终端执行上面的命令。默认会打印以下连接说明，然后保持前台运行；连接建立后，回到原终端重跑审计：

```text
Starting prod ClickHouse SSH tunnel:
  local  127.0.0.1:19000
  remote goldenshare-prod:127.0.0.1:9000
```

这段打印只是连接目标说明，不是查询成功证明；若随后出现SSH错误，先处理错误。

默认将本机 `127.0.0.1:19000` 转发至 `goldenshare-prod` 的9000端口。按 Ctrl-C 会关闭隧道。隧道已经运行时不要重复启动；端口冲突应先确认现有进程，不要直接杀进程。

本机 ClickHouse 启动成功，不会自动启动这条隧道。审计若报 `127.0.0.1:19000 Connection refused`，表示 prod 连接不可用，不能当成 prod 缺数据。

## 2. 按指定日期审计并生成报告

本节于2026-10-31对齐审计脚本版本2；下方9月报告路径仅保留为当时的文件名示例，不代表当前版本的数据验收结果。

使用现有 skill 脚本和 orchestrator 已安装的 Python，不使用可能自动同步依赖的 `uv run`。下面通过 Bash 登录环境加载已配置的数据库环境变量，不打印账号、密码或 token。

### 审计一天

只改 `--date` 后的日期：

```bash
/bin/bash -lc '
  cd /Users/congming/github/goldenshare/lake_console/orchestrator || exit 1
  exec .venv/bin/python -B \
    /Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py \
    --lake-root /Volumes/datasource/data_lake \
    --date 2026-09-15 \
    --output-dir /private/tmp
'
```

**例子：**要检查9月15日，直接执行上面的完整命令；要检查9月16日，只将 `--date 2026-09-15` 改成 `--date 2026-09-16`。命令只读正式数据、写临时报告。此前9月15日实际生成的报告为：

```text
/private/tmp/dg_dataset_audit_20260915_20260916T034832Z.json
```

你的本次报告时间戳会不同，以终端打印的 `report` 为准。

### 一次审计多天

```bash
/bin/bash -lc '
  cd /Users/congming/github/goldenshare/lake_console/orchestrator || exit 1
  exec .venv/bin/python -B \
    /Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py \
    --lake-root /Volumes/datasource/data_lake \
    --date 2026-09-14 --date 2026-09-15 \
    --output-dir /private/tmp
'
```

**例子：**想一次检查9月14日和15日，直接执行上面的命令，得到两份报告，而不是一个日期区间的合并报告。还要检查16日，就追加 `--date 2026-09-16`。不写数据、不补跑任务；同周/月文件共用一次统计，同一年度文件族按所请求日期一次分组计数。重复的相同日期只处理一次。

每个日期生成独立 JSON 报告，终端输出的 `report` 字段是准确路径。默认形如 `/private/tmp/dg_dataset_audit_20260915_<UTC时间戳>.json`。可将 `--output-dir` 改为自己的报告目录，报告不写进正式 Lake。

脚本从当前 `LAKE_ASSET_CATALOG` 和分区模型获取审计范围。原日表、股票年度文件及本机/prod ClickHouse、prod PostgreSQL均做指定日期计数；新增股票周/月Raw和Silver四项及自然日公告Raw一项。周/月文件检查实际观察到的更新截至日期，公告允许合法零行。按当前目录，180项中164项纳入、16项明确排除，实际数量以本次报告为准。

两项交易日历不作为独立审计项；只读取周/月判断需要的Silver SSE日期依据，Raw日历不读取。其余排除项为13项全量快照和1项湖健康，排除不代表已废弃或已经验收。脚本不需要启动DG网页，不读取Dagster instance，不写正式数据，也不触发原job或检查。

| 报告字段 | 人话解释 |
| --- | --- |
| `report_schema_version` | 当前为2；历史报告不改写 |
| `catalog_classification_complete` | 必须为true；所有catalog资产都有审计或明确排除归属 |
| `audit_passed` | 本次声明范围内，无缺口、等待、未核实或分类问题；不代表全市场代码覆盖、全部质量检查或历史任务成功 |
| `missing_file_asset_keys` | 已确认缺Parquet或零字节；不可读单列未核实 |
| `missing_date_rows_asset_keys` | 年度文件族不存在，或成功计数确认该日0行；读取失败不进入此清单 |
| `present_zero_row_asset_keys` | 文件可读但0行，单独判断该数据集是否允许空日 |
| `allowed_zero_row_asset_keys` | 公告合同允许的可读0行；未检查源交付是否完成 |
| `missing_serving_asset_keys` | 数据库能连接，但该日没有行 |
| `update_behind_asset_keys` | 周/月文件有合法旧日期，但未达到本次应更新日；缺文件、零行、全NULL不混入 |
| `data_gap_asset_keys`、`pending_asset_keys` | 已确认缺口、源窗口尚未结束的等待项 |
| `unverified_asset_keys`、`unverified_serving_asset_keys` | 无法完成核验的全部项及其中Serving项，不等于已确认缺失 |
| `period_partition_assets` | 四项周/月结果，分别给出周期、应更新日期、实际最大截至日期及最终判断 |
| `natural_date_partition_assets` | 指定自然日公告结果；`source_delivery_status=not_checked` |
| `excluded_assets` | 按本次明确范围排除的日历、快照和湖健康项，不等同于无用或通过 |

进程退出码0只表示报告生成成功，数据结论看`audit_passed`及相应清单。Lake根或共享DuckDB连接初始化失败会报错、非0退出；开始后的单项读取失败列未核实，其它正常项继续，不自动重试。

周/月更新状态和最终判断分开：缺文件时没有可观察的更新日期，但在源窗口结束后可以明确判为缺口，不能仅凭`update_status=unverified`把整项也算作未核实。源窗口按应更新开市日20点解释，不能当成Silver任务超时，也不能在周六继续等周六20点来掩盖周五缺口。更新到更晚日期只能说明当前文件已覆盖，不能证明历史当天任务成功。

开发验收使用隔离小样本，不执行正式目录审计。后续只在明确日期审计任务下判断必要范围、复用适用证据；收尾只汇总已取得的结果，不为新增五项重扫原159项，不做额外全局明细读取或重复全局审计。

## 3. 手动注册某个数据集的日期分区

### 先分清它会做什么

注册日期只是让DG认识这个日期，**不会生成Parquet，不会补materialization/check，也不直接启动run**。但是正在运行的sensor可能在下一tick发现新日期并自动提交任务。

注册对象是动态分区集合，不是独立资产。例如多个资产使用同一个交易日集合时，新增日期会同时对这些资产可见。因此先查真实集合，再决定是否注册。不要凭资产名称猜集合，也不要把股票代码集合当日期集合。

以下命令需要本机DG已启动在 `http://127.0.0.1:3000`，且code location已加载最新代码。正式写入只在你确定需要补注册后执行。

### 第一步：只读查资产对应的分区集合

将示例里的 `raw_tushare_daily_basic` 换为目标资产的准确名称：

```bash
curl --fail-with-body -sS http://127.0.0.1:3000/graphql \
  -H 'Content-Type: application/json' \
  --data '{"query":"{ assetNodeOrError(assetKey:{path:[\"raw_tushare_daily_basic\"]}) { __typename ... on AssetNode { partitionDefinition { type name } } } }"}'
```

**例子：**想给“每日指标”补日期，但不知道它属于哪个分区集合，先执行上面的只读命令。当前核验过的返回如下：

```json
{"data":{"assetNodeOrError":{"__typename":"AssetNode","partitionDefinition":{"type":"DYNAMIC","name":"cn_a_daily_basic_trade_days"}}}}
```

因此下一步使用的是 `cn_a_daily_basic_trade_days`，不是资产名 `raw_tushare_daily_basic`。

每日指标目前应返回 `type=DYNAMIC`、`name=cn_a_daily_basic_trade_days`。若资产不存在、结果含 `errors`、分区为null或不是DYNAMIC，停止，不套用下一条命令。

还可在DG资产页的Partitions区域查看已注册日期。要增加的日期必须是该数据集适用市场的交易日，且不早于其历史起点；检查对应交易日历和数据集合同。GraphQL只负责加key，不替你验证交易日、历史边界或上游数据。

### 第二步：明确写入一个日期

下面是**正式分区写入命令**，不是dry-run。先将 `partitionsDefName` 改为上一步查到的集合，将 `partitionKey` 改为实际需要的ISO日期。示例日期可能已经存在。

```bash
curl --fail-with-body -sS http://127.0.0.1:3000/graphql \
  -H 'Content-Type: application/json' \
  --data '{"query":"mutation { addDynamicPartition(repositorySelector:{repositoryLocationName:\"orchestrator\",repositoryName:\"__repository__\"},partitionsDefName:\"cn_a_daily_basic_trade_days\",partitionKey:\"2026-09-15\") { __typename ... on AddDynamicPartitionSuccess { partitionsDefName partitionKey } ... on DuplicateDynamicPartitionError { message } ... on PythonError { message } ... on UnauthorizedError { message } } }"}'
```

**例子：**假设已经核对9月15日是适用交易日，而且每日指标确实没有注册这天，就执行上面的写入命令。成功返回应类似以下示意（不是本次实际写入记录）：

```json
{"data":{"addDynamicPartition":{"__typename":"AddDynamicPartitionSuccess","partitionsDefName":"cn_a_daily_basic_trade_days","partitionKey":"2026-09-15"}}}
```

如果要注册9月16日，只改 `partitionKey` 为 `2026-09-16`，但仍须先核对该日是否适用、是否已注册。执行后刷新DG资产页，看到日期只代表注册成功；是否已有数据、是否成功更新，要另看物理审计和run/check结果。已开启的sensor可能因此自动开始补数。

| 返回类型 | 处理方式 |
| --- | --- |
| `AddDynamicPartitionSuccess` | 此日期已新增，返回集合名和日期；刷新资产Partitions页确认 |
| `DuplicateDynamicPartitionError` | 日期原本就存在，无需删除重建 |
| `PythonError` / `UnauthorizedError` / 顶层 `errors` | 未确认成功，先排查，不继续批量写入 |

GraphQL可能以HTTP 200返回业务错误，所以仍要检查JSON结果，不能只看curl是否退出0。该操作通过DG官方API，不直接改PostgreSQL。多天或多个集合先列清单，再逐项执行；本手册不提供绕过交易日核验的一键全量注册。

如果返回仓库/集合不存在，先在网页检查code location和repository；当前本机为 `orchestrator / __repository__`。不要创建同名新集合来掩盖未加载definitions的问题。

## 4. 本次核验与边界

- ClickHouse命令按当前两个 `lake_console/bin` 脚本逐项核实；本次未启动服务或隧道。
- 审计入口已在2026-09-16实际审计2026-09-15，覆盖161个catalog项；报告位于 `/private/tmp/dg_dataset_audit_20260915_20260916T034832Z.json`。此报告仅证明当时状态。
- 分区查询已对正式DG只读验证，确认每日指标使用 `cn_a_daily_basic_trade_days`。
- 注册mutation参数及返回类型依据当前安装的 `dagster_graphql/schema/roots/mutation.py` 和 `schema/partition_sets.py`；本次未执行mutation、未写正式分区。
- 无新增生产工具或依赖，无资产、job、sensor、schema、路径或调度行为改动。命令仅整理已有能力。
