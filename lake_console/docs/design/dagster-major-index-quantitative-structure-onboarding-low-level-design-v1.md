# DG 主要指数量化结构 Gold 数据集详细设计 v1

2026-11-09。依据 [接入方案](dagster-major-index-quantitative-structure-onboarding-plan-v1.md) 和 [DG 数据集接入模板](../templates/dagster-dataset-onboarding-template.html) 编写。每日全量重算和上海时间 18:00 开始检查已确认。本文定义开发及正式执行步骤，保留功能与数据读回小样。

## 1. 实现边界

DG 部分新增 `major_index_quantitative_structure` Gold 数据集。读取现有 DG 指数日线技术因子、四个分钟周期的 K 线与 MACD 以及 SSE 交易日历。使用现有 r4.1 规则生成量化结构事件，日线和分钟分别从 2010-01-04 或各自更晚的有效起点连续计算。字段、指数范围和有效日期按原方案第 1–3 节。财势乾坤的读取与验收见 [§8](#8-财势乾坤接入详细设计)。

| 文件位置（相对 Orchestrator 的 `src/orchestrator/`） | 改动 |
| --- | --- |
| `defs/catalog/lake_assets.py`、`defs/catalog/name_mapping.py`、`defs/run_contracts/asset_column_schemas.py` | 登记资产、分区模型、中文名和物理字段 |
| `defs/run_contracts/major_index_quantitative_structure.py` | 共用的资产与检查名称、九指数和周期范围、起点及触发时间 |
| `defs/partitions.py`、`defs/paths.py` | 定义独立交易日分区、正式文件及候选路径 |
| `defs/assets/major_index_quantitative_structure.py`、`defs/io/major_index_quantitative_structure.py` | 历史读取、逐根计算和按日结果写入。日更与 bootstrap 共用 |
| `defs/checks/major_index_quantitative_structure_checks.py` | 定义并复用两项结果检查 |
| `defs/jobs/major_index_quantitative_structure_update.py`、`defs/sensors/major_index_quantitative_structure_trade_day_sensor.py`、`defs/sensors/gold_major_index_quantitative_structure_update_job_sensor.py` | 单日 job、日期注册和日更触发 |
| `defs/bootstrap/major_index_quantitative_structure_history_cli.py` | 历史计划、分区登记、候选生成、文件验收及事件补录 |

复用现有 DG 资源、RunRequest、run key、cursor、metadata 和检查记录的构造方法。配置仍由现有 Lake 路径及 DuckDB 资源提供。日更手动入口只选择交易日分区，历史命令只接受已核准的日期范围。业务边界只影响新增 Gold 及其写入入口。

日更和历史批量入口共用 `defs/io/major_index_quantitative_structure.py` 中的计算和写入逻辑。计算按交易日升序返回当天结果和输入根数，写入逻辑校验候选文件并替换正式文件。日更只写目标分区，历史批量入口写获批范围内的每个交易日。

## 2. r4.1 的交付与输入

共享包 `goldenshare-technical-indicators==0.1.0` 已随 `42acc9928` 交付，财势乾坤回归与 DG 隔离安装验收已完成。DG 从 `goldenshare_technical_indicators.xxm` 导入 `XxmCalculator`、`XxmBar` 和 `MAIN_SPEC`，从 `goldenshare_technical_indicators.xxm.event_display` 导入 `event_display_flags`。r4.1 只用 Python 标准库。DG 已有 DuckDB 负责取数与写入。 [共享包验收](../../../docs/architecture/calculation-operator-shared-package-low-level-design-v1.md#8-实现与验收记录) · [共享包入口](../../../packages/technical_indicators/src/goldenshare_technical_indicators/xxm/__init__.py)

DG 接入时在 `lake_console/orchestrator/pyproject.toml` 声明 `goldenshare-technical-indicators==0.1.0; python_version >= '3.13'`，`[tool.uv.sources]` 用 `../../packages/technical_indicators` 作为同仓解析来源，同步更新 DG 的 `uv.lock`。DG 项目原有的 `requires-python` 范围保留。共享包在执行本数据集计算时导入，正式 DG 使用现有 Python 3.13 环境。 [现有 DG 依赖](../../orchestrator/pyproject.toml) · [共享包版本与 Python 要求](../../../packages/technical_indicators/pyproject.toml)

正式环境安装和加载按 [§2.2](#22-正式-dg-安装与加载) 执行。

识别内核接收收盘价和已经算好的 DIF、DEA、MACD 柱值。DG 日线读取 `index_factor_pro`，分钟读取 `major_index_mins` 和 `major_index_mins_technical`。财势乾坤日线图使用现有通用技术指标计算，下一根预判使用现有 `projection.py` 根据假设收盘价推算指标。这两处计算继续由各自的现有入口调用。 [DG 分钟技术指标](../../orchestrator/src/orchestrator/defs/io/major_index_mins_technical_writer.py) · [财势乾坤日线图入口](../../../src/app/dependencies/index_daily_technical_indicators.py) · [下一根预判的 MACD 计算](../../../src/biz/services/wealth/market/index_detail_xxm/projection.py)

**执行方式已确认。** 日更和人工重跑均从历史起点重新计算到目标日。内核在一次运行内按 K 线顺序更新前一根留下的识别状态，按日处理对齐后的数据，每天至多 162 根。DuckDB 负责 Parquet 读取、列投影、对齐和写入。正式历史读取和写入按第 5 节审批。 [Orchestrator Parquet 计算门禁](../../orchestrator/AGENTS.md)

### 2.1 单日输入及计算顺序

1. 以目标分区日为日更计算终点。日更和首次初始化共用[方案 §1 的九个指数代码](dagster-major-index-quantitative-structure-onboarding-plan-v1.md#1-目标与范围)。对正在计算的 SSE 交易日 `d`，日线取九个代码与 `active_idx_factor_pro_daily_codes(d)` 的交集，分钟取九个代码与 `effective_silver_codes_for_date(d)` 的交集。计算下限为 2010-01-04。DuckDB 按各自的交集过滤输入，再核对根数和时间键。上游的科创综指（`000680.SH`）和北证50（`899050.BJ`）由同一名单过滤，既不计入应有根数，也不进入计算和结果。 [日线范围](../../orchestrator/src/orchestrator/defs/run_contracts/idx_factor_pro.py#L216) · [分钟范围](../../orchestrator/src/orchestrator/defs/run_contracts/major_index_mins.py#L324)
2. 投影日线 `ts_code, trade_date, close, macd_dif_bfq, macd_dea_bfq, macd_bfq`。四个分钟周期各自按 `(ts_code, freq, trade_date, trade_time)` 对齐价格和指标，复用 `expected_gold_minute_times("SSE", freq)` 取得应有的完成时刻。对同一批输入按日期、指数、周期统计有效键，每个应有键对应一条完整日线或一对完整分钟记录。应有键缺失或重复时报告日期、指数、周期和时间键。核对通过后直接用这批输入计算。 [DG 完成时刻](../../orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py#L169)
3. 各序列按完成时刻升序调用内核。日线使用日期。分钟使用上海时区 `+08:00`。创建内核时沿用 `period|首根完成时刻|指标口径` 的来源标识写法，日线口径为 `bfq`，分钟口径为 `major_index_mins_technical.INDICATOR_VERSION`。每次运行均从各序列有效起点的空状态开始。 [来源标识](../../../src/biz/queries/wealth/market/index_detail_xxm/query_service.py)
4. 每个指数的每个周期各自使用一个计算器。算完一根 K 线，只用这一根产生的事件判断图上画哪些标记，结果填入 `display_on_chart`。随后按完成时刻、指数代码、周期汇总当天结果。日线按 15:00 排序，存储时仍为空。同一根 K 线保留内核发出的事件顺序。

### 2.2 正式 DG 安装与加载

本机正式 DG 使用 `/Users/congming/github/goldenshare/lake_console/orchestrator` 的 `.venv/bin/python3`，code location 为 `orchestrator`，定义从 `src/orchestrator/defs` 加载。目标实例目录为 `/Users/congming/.goldenshare/dagster_home`。接入前核对正式工作目录和获准代码版本。当前本需求验收的代码提交为 `a4bebf883`。以下两条检查的输出均应为空。若发现会被加载的其他改动，先确认正式部署的源码范围再继续。 [本机启动入口](../../bin/lake-dg-start) · [定义装配](../../orchestrator/src/orchestrator/definitions.py)

```bash
cd /Users/congming/github/goldenshare
git diff --name-only a4bebf883 -- lake_console/orchestrator/src lake_console/orchestrator/pyproject.toml lake_console/orchestrator/uv.lock lake_console/bin/lake-dg-start packages/technical_indicators
git ls-files --others --exclude-standard -- lake_console/orchestrator/src lake_console/bin/lake-dg-start packages/technical_indicators
```

获准安装后执行下列命令。当前找到的 wheel 位于 `/private/tmp`，使用前重新核对文件和哈希。此前隔离验收仅安装到临时副本，正式环境的安装与加载单独确认。 [共享包交付与哈希](../../../docs/architecture/calculation-operator-shared-package-low-level-design-v1.md#8-实现与验收记录)

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
wheel=/private/tmp/goldenshare-operator.rodKJR/wheels/goldenshare_technical_indicators-0.1.0-py3-none-any.whl
expected_sha256=5fc911ef9215847e1400d56ad95428c38d38e0af828b8dea568786b3b4730913
test "$(shasum -a 256 "$wheel" | awk '{print $1}')" = "$expected_sha256" &&
  uv pip install --offline --no-deps --reinstall-package goldenshare-technical-indicators --python .venv/bin/python3 "$wheel" &&
  .venv/bin/python3 -IB - <<'PY'
import sys
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path
from goldenshare_technical_indicators import xxm

assert version("goldenshare-technical-indicators") == "0.1.0"
assert xxm.MAIN_SPEC.algorithm_version == "xxm-direction-v0.5-r4.1"
assert Path(xxm.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert Path(find_spec("orchestrator").origin).resolve().parent == Path.cwd() / "src/orchestrator"
print(sys.executable, xxm.__file__, xxm.MAIN_SPEC.algorithm_version)
PY
```

正式 DG 已运行时，在 [DG 控制台](http://127.0.0.1:3000) 打开 **Deployment → Code locations**，只对 `orchestrator` 点 **Reload**。DG 尚未运行时，获准后用现有入口启动 `bash /Users/congming/github/goldenshare/lake_console/bin/lake-dg-start`。在同一实例确认 code location 加载成功，能查到 §4 的 Asset、Job、两项检查和两个 Sensor，并确认两个 Sensor 都是停用。安装、重载或启动失败时停在此步，记录版本或加载错误，保留两个 Sensor 停用。 [Dagster 代码位置操作](https://docs.dagster.io/guides/operate/webserver#deployment) · [本机启动方案](dagster-local-startup-plan-v1.md)

## 3. 结果和日更写入

### 3.1 文件合同

正式文件为 `/Volumes/datasource/data_lake/gold/indicator/major_index_quantitative_structure/trade_date=YYYY-MM-DD/part-000.parquet`。一个日期一行，列顺序为 `trade_date DATE`、`success BOOLEAN` 和下列 `results` 类型。日线的 `bar_end_time` 为空，其余业务值非空。空列表按声明类型写入。

```sql
STRUCT(
  ts_code VARCHAR,
  period VARCHAR,
  bar_end_time TIME,
  event_type VARCHAR,
  direction VARCHAR,
  display_on_chart BOOLEAN
)[]
```

正式 Gold 目录保存按日 Parquet。识别状态只在当次运行内存中使用。首次初始化仅记录哪些日期的文件已写完，见第 5.2 节。

### 3.2 按日提交与重跑

日更和人工重跑都先核对目标日上游就绪，再用 DuckDB 从历史起点读取并对齐到目标日的输入。只保留目标日的事件和结果。结果先写到 `/Volumes/datasource/data_lake_staging/major_index_quantitative_structure/<run_id>/`，读回通过后用同文件系统 `os.replace()` 替换目标日文件。

某天漏写、结果错误或作业中断，都在 DG 用同一个 `gold_major_index_quantitative_structure_update_job` 选择该交易日分区重跑。超出 sensor 的 10 日窗口也按此处理。若本资产的分区键缺失，先登记该日。若缺的是上游历史输入，先由相应的上游任务补齐，再重跑目标日。重跑完成以目标日的最新产出和关联的两项通过检查为准。无需另设历史恢复入口。

| 结果 | 处理 |
| --- | --- |
| 成功，有或无事件 | 目标日写 `success=true`，通过两项检查后记为完成 |
| 开始计算前上游尚未就绪 | Sensor 等待。若 job 已启动，资产函数记录等待原因后无输出结束。使用 `output_required=False`，无输出分支直接退出，既不写结果文件也不登记产出，两项检查随资产跳过。人工发起的这次运行不占自动 run key，上游齐备后可自动触发 |
| 已确认的输入或识别失败 | 任一应有日期确认输入缺失或识别失败，停止计算，写目标日 `success=false, results=[]` 并登记产出。合同检查通过，完成检查返回 `passed=False`、`severity=ERROR`，由该阻断检查使 job 失败。日志记录实际失败的日期、指数和周期 |
| 作业中断或验收未完成 | 手动重跑目标日，从历史起点重新计算并替换该日结果 |

资产函数用生成器，只在实际写出结果后 `yield MaterializeResult`。自动运行已占用日期 run key 后若复核发现上游未就绪，等上游就绪后手动重跑同一分区。一次人工提前尝试仍按上表处理。 [Dagster 条件产出](https://docs.dagster.io/api/dagster/assets#dagster.asset) · [Sensor run key](https://docs.dagster.io/guides/automate/sensors)

日更与历史补录使用同一份产出 metadata。日期使用产出的分区键，以下字段通过 `build_materialization_metadata` 写入。

| 字段 | 值 |
| --- | --- |
| `dagster/uri` | 实际正式 Parquet 路径 |
| `dagster/row_count` | 结果文件的行数，有产出时为 1 |
| `goldenshare/observed_columns` | `trade_date`、`success`、`results` |
| `goldenshare/formula_version` | `MAIN_SPEC.algorithm_version`，沿用主要指数九转的字段名 |
| `goldenshare/source_row_count` | 本分区当天实际送入内核的 K 线根数，分钟对齐后每根计一次。失败发生在更早日期时为 0。全程计算根数记在运行日志 |
| `goldenshare/event_count` | 本分区 `results` 中的条数，包括保存但不在普通图上标记的事件 |

`goldenshare/event_count` 是本数据集新增的产出 metadata 字段，开发时同步登记到运行合同和相关静态检查。Parquet 仍使用 §3.1 的字段。 [现行产出 metadata helper](../../orchestrator/src/orchestrator/defs/run_contracts/metadata.py#L172) · [主要指数九转版本字段](../../orchestrator/src/orchestrator/defs/bootstrap/major_index_nineturn_events.py#L645)

日更 job、人工重跑和历史批量入口共用 staging 下 `major_index_quantitative_structure/writer.lock`，复用现有文件锁做法。取到锁的作业才写入。历史行情修订后先确认受影响的分区，再按本节补跑。首次初始化和算法换版全量替换按第 5 节执行。 [现有写入锁](../../orchestrator/src/orchestrator/defs/io/index_daily_writer.py#L128)

## 4. Dagster 定义和日更

| 对象 | 定义 |
| --- | --- |
| Asset | `gold_major_index_quantitative_structure`，`Gold / INDEX_TOPIC / index`，字段合同 `major_index_quantitative_structure_v1` |
| 分区 | `TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_QUANTITATIVE_STRUCTURE`，动态分区集 `cn_major_index_quantitative_structure_trade_days` |
| Job | `gold_major_index_quantitative_structure_update_job`，选择本资产和下面两项检查，手动运行只选择日期 |
| 注册 sensor | `major_index_quantitative_structure_trade_day_sensor`，最近 10 个已完成开市日，单次最多补 2 个键 |
| 日更 sensor | `gold_major_index_quantitative_structure_update_job_sensor`，单次最多一个交易日 |
| 结果合同检查 | `gold_major_index_quantitative_structure_result_contract_check`，校验物理列、单日一行、日期、事件类型和空列表语义 |
| 完成检查 | `gold_major_index_quantitative_structure_completion_check`，校验 `success=true` |

两项检查都显式绑定资产的分区定义，使用 `blocking=True`，写标准检查范围、检查数及失败样本。合法的失败行可通过合同检查，由完成检查阻断。检查只读已写出的结果，事件业务顺序由金样本证明。字段定义在 `defs/run_contracts/asset_column_schemas.py`，路径函数在 `defs/paths.py`，动态分区定义在 `defs/partitions.py`。资产、检查、job、sensor 和历史入口按各自职责引用这些定义。Catalog 引用相同定义用于登记和静态检查。Metadata、tags 与中文说明按原方案第 5 节。 [DG 检查规范](../templates/dagster-dataset-onboarding-template.html#checks) · [Catalog 规则](../../orchestrator/AGENTS.md#asset-catalog-registry-门禁)

两个 sensor 默认停用，最短检查间隔 600 秒。每日按 `Asia/Shanghai` 判断时刻，18:00 前直接返回 `SkipReason`，不读日历或 DG 状态。18:00 起查 SSE 日历，开市日包含当天，休市日只包含之前的开市日。仍未处理的旧交易日，在下一次允许检查时按日期优先处理。 [现有 18:00 注册示例](../../orchestrator/src/orchestrator/defs/sensors/stock_mins_trade_day_sensor.py)

日历在 SQL 中限制为最近 10 个已完成开市日。注册 sensor 按日期用 `has_dynamic_partition` 查注册状态，最多查 10 个，找到 2 个缺失键即提交一次注册请求。更新 sensor 调一次 `get_asset_check_partition_info` 获取这 10 日的两项检查。两项状态均为 `SUCCEEDED`、均有最新产出 ID，且各自的检查目标 ID 等于该日产出 ID，才视为已完成。

更新 sensor 只检查最早未完成日 `D`。用 `has_dynamic_partition` 核对三个分区集的日期键，并按日更 job 名和 `dagster/partition=D` 查询最近一次运行。正在执行则等待。另用 `fetch_materializations(AssetRecordsFilter(asset_key=本资产, asset_partitions=[D]), limit=1)` 查当天实际最新产出。已有产出时，两项检查须通过并指向该产出，缺任何一项就停在 `D`。最近一次运行失败、取消，或带当天自动 run key 但跳过产出时，同样提示用原 job 人工重跑。其余情况复用 `partition_dataset_readiness_status_from_latest_checks` 核对九个上游资产最新产出及 31 项阻断检查。全部通过才提交一个 `partition_key=D` 的 `RunRequest`。按统一 builder 生成日期 run key。 [现有同日检查](../../orchestrator/src/orchestrator/defs/sensors/readiness.py#L808)

一个有效 tick 读取一份日历，最多调用 DG 状态接口 16 次。分别为本资产批量完成检查 1 次、三个分区集 3 次、最近运行 1 次、本资产目标日最新产出 1 次、九个上游产出 9 次和上游批量检查 1 次。复用现有 sensor cursor 的 `target_date` 记录仍未完成的日期。该日期已移出最近 10 个开市日时，先单独核对它的完成检查，本次不推进后续日期。已完成就清除该日期，下次恢复常规检查。仍未完成就提示用同一个日更 job 选择该分区，缺分区时先登记。上游历史输入有缺失时，由原上游任务修好再重跑。

## 5. 首次历史初始化和算法换版

### 5.1 计划与审批

使用直写补录。日期按 SSE 日历从 **2010-01-04** 到批准的截止日。功能小样通过后，按应有输入文件是否存在确定最后一个连续可用的交易日作为候选截止日。每个序列沿用自己的有效起点。计划冻结日期和版本，统计输入文件、已存在目标和预计根数，核对 Lake 可用空间。正式计算时用实际读入的 K 线核对根数和时间键。全历史读取、分区登记、正式写入和事件补录按各自范围确认。

| 用途 | 计划和文件处理 |
| --- | --- |
| 首次初始化 | `plan` 默认生成初始化计划，`replace_all=false`。若计划列出了原有目标文件，停在计划阶段。已获批的同一计划中断后按 §5.2 重跑 |
| 算法换版 | 用新版内核运行 `plan --replace-all`，计划写 `replace_all=true`。截止日必须覆盖已有的最新 Gold 文件日期。计划列出要替换的全部已有文件并冻结新版算法版本。获批后用同一 `build` 一次计算整段历史，逐日替换，文件验收后为各日登记新版产出和两项检查 |

正式历史批量执行安排在获批维护窗口，两条 sensor 从写入前保持停用，文件和 DG 事件验收完成后再按 §5.5 启用。

2026-11-06 是历史只读实测的截止日。该范围内 4,089 个开市日对应 36,801 份行情和指标文件，实际对齐得到 530,292 根输入。正式执行以当次获批计划为准。 [方案中的来源与预算](dagster-major-index-quantitative-structure-onboarding-plan-v1.md) · [全历史只读实测](#61-开发前全历史读取与识别计时)

**只读确定本次截止日。** 先从 SSE 日历取得探查上限。按上海时间，18:00 起可纳入当天的开市日，之前只纳入更早开市日。再用现有 `plan --through` 检查从 2010-01-04 起的九路文件。此步只查询日历和文件路径、大小，报告写入 `/private/tmp`。 [日历查询](../../orchestrator/src/orchestrator/defs/io/major_index_quantitative_structure.py#L71) · [历史计划实现](../../orchestrator/src/orchestrator/defs/bootstrap/major_index_quantitative_structure_history_cli.py#L98)

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
bootstrap_module=orchestrator.defs.bootstrap.major_index_quantitative_structure_history_cli
report_dir=$(mktemp -d /private/tmp/major-index-quantitative-structure.XXXXXX)
probe_plan="$report_dir/probe-plan.json"
reviewed_plan="$report_dir/plan.json"
reviewed_file_audit="$report_dir/file-audit.json"
reviewed_event_plan="$report_dir/event-plan.json"

read_structure_calendar() {
  .venv/bin/python3 -IB - "$@" <<'PY'
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.duckdb_connection import DuckDBConnectionSettings, connect_configured_duckdb
from orchestrator.defs.io.major_index_quantitative_structure import structure_trade_dates
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.run_contracts.major_index_quantitative_structure import (
    STRUCTURE_CHECK_START, STRUCTURE_SENSOR_LOOKBACK,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE

now = datetime.now(CN_A_SENSOR_TIMEZONE)
through = now.date() if now.time() >= STRUCTURE_CHECK_START else now.date() - timedelta(days=1)
recent = None if len(sys.argv) > 1 else 1
with TemporaryDirectory(dir="/private/tmp") as temp:
    settings = DuckDBConnectionSettings(temp_directory=Path(temp))
    with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as connection:
        days = structure_trade_dates(connection, Path(DEFAULT_LAKE_ROOT), through, recent=recent)
if not days:
    raise SystemExit("SSE 日历没有可用交易日")
if len(sys.argv) == 1:
    print(days[-1])
else:
    completed_through = date.fromisoformat(sys.argv[1])
    due = [day for day in days if day > completed_through]
    recent_days = set(days[-STRUCTURE_SENSOR_LOOKBACK:])
    print(json.dumps({
        "eligible_through": str(days[-1]),
        "due_dates": [str(day) for day in due],
        "outside_sensor_window": [str(day) for day in due if day not in recent_days],
    }))
PY
}

probe_through=$(read_structure_calendar) &&
  .venv/bin/python3 -IB -m "$bootstrap_module" plan --through "$probe_through" --output "$probe_plan"
```

查看探查报告的 `first_missing_input`。为空时，探查上限就是候选截止日，直接复用该计划。有值时，取报告中首个缺文件日的上一条 SSE 开市日作为截止日。首日就缺文件时停在计划阶段，由上游补齐后再探查。下列命令仅在探查报告已成功生成后执行。

```bash
history_through=$(.venv/bin/python3 -IB - "$probe_plan" <<'PY'
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text())
missing = plan["first_missing_input"]
if not missing:
    print(plan["through"])
else:
    days = [row["trade_date"] for row in plan["partitions"]]
    index = days.index(missing["trade_date"])
    if index == 0:
        raise SystemExit(f"历史首日缺文件：{missing['path']}")
    print(days[index - 1])
PY
) && if [ "$history_through" = "$probe_through" ]; then
  cp "$probe_plan" "$reviewed_plan"
else
  .venv/bin/python3 -IB -m "$bootstrap_module" plan --through "$history_through" --output "$reviewed_plan"
fi
```

审阅 `reviewed_plan` 中的 `through`、`plan_id`、文件数、预计 K 线根数、结果文件数和可用空间。首次初始化要求 `replace_all=false`、`first_missing_input=null`、`existing_targets=[]`。获准的截止日与计划 ID 供 §5.4 使用。此处确认到文件存在为止，实际 K 线时间键和根数在 `build` 读取同一批输入时核对。

### 5.2 文件阶段

| 动作 | 执行和验收 |
| --- | --- |
| `sample` | 获准后只读从 2010-01-04 起的首两个 SSE 开市日，用正式计算与候选检查写入 `/private/tmp` 的样本目录。核对输入根数、结果行数、事件数和读回内容。 |
| `plan` | 只读规划。在 `/private/tmp` 下输出 `plan_id`、`replace_all`、开始日、截止日、算法版本、升序交易日清单，以及各日输入路径、目标路径和预计根数。记录已有目标和合计数量。范围内有缺失的输入文件时报告首个缺失日和路径 |
| `register` | 获批后，在正式 DG instance 仅批量登记计划缺少的本资产日期键。用同一 instance 读回并核对。两个 sensor 保持停用 |
| `build` | 一次处理整个获批范围。复用日更的计算代码，从首日开始连续计算，DuckDB 内部分批读入。当天核对 K 线根数和时间键后用同一批输入计算。逐日写候选、读回校验并原子提升，再保存该日完成位置。遇到上游输入或识别失败就停在当天，历史初始化只提升成功结果 |
| `post-audit` | 核对计划日期与实际文件集合。分批汇总结果，核对每个日期一行且成功，统计事件数，并与 `latest.json` 的末日、版本和累计数量对账。报告记录 `plan_id`、算法版本及各日的分区键、正式路径、输入根数、结果行数和事件数，供事件阶段复用。输入根数取写入时已核对一致的计划根数。字段合同以各日提升前的校验为准 |

计划标识 `plan_id` 由冻结的范围、版本、路径清单和 `replace_all` 生成。写入命令核对报告内容算出的标识与传入标识一致，`build` 开始前核对运行内核版本与计划一致。候选文件和 `latest.json` 放在 `/Volumes/datasource/data_lake_staging/major_index_quantitative_structure/<plan_id>/`。进度文件只记 `plan_id`、算法版本、最后写完的交易日、累计结果行数和事件数，每日正式文件提升后原子替换。日更不读取此文件。

重跑同一计划时，仍从 2010-01-04 开始计算，跳过进度文件已确认完成的日期写入。若 4 日的文件已提升、进度仍是 3 日，则重算后重写 4 日，再继续 5 日。未完成候选直接丢弃。计划中原已存在的目标文件，仅在获批全量替换范围内覆盖。日更重跑和历史初始化重跑均不保存或读取识别内核的跨日状态。

### 5.3 Dagster 事件阶段

文件验收后，`events-plan` 用 `post-audit` 的成功日期和每日报告与同一正式 instance 对账。内部按自然月分批，用 `get_latest_storage_id_by_partition` 查询最新产出 ID，再用 `fetch_materializations` 按 ID 取产出元数据。两项检查用 `get_asset_check_partition_info` 查同批日期。每批最多 31 个产出记录和 62 个检查状态。首次初始化列出缺产出、缺检查和已有通过，现有失败或元数据不符时报告处理。批准换版时，将已替换文件但最新产出仍为旧版本的日期列入新版产出清单。 [现行分区检查批量对账](../../orchestrator/src/orchestrator/defs/bootstrap/daily_basic_events.py)

获批后 `events-apply` 先写获批样本分区，读回确认该日产出、两项检查及关联正确，再用一次命令补录获批范围。每个成功分区至多补一条当前版本产出和两条检查。产出使用 `report_runless_asset_event(AssetMaterialization(...))`，检查按主要指数九转现行方式写入带日期和目标产出的 `AssetCheckEvaluation`。已有符合文件验收报告的当前产出则复用，检查只补缺少或尚未指向当前产出的项。获批换版追加新版产出，两项检查绑定该产出。`events-audit` 对账实际产出与两项检查的日期集合，抽查分区归属。 [主要指数九转事件写入](../../orchestrator/src/orchestrator/defs/bootstrap/major_index_nineturn_events.py) · [Dagster 事件接口](https://docs.dagster.io/api/dagster/external-assets-instance-api)

文件和事件均验收后，按 [§5.5](#55-启用并验收日更) 接到日更。

### 5.4 操作入口

继续使用 §5.1 的工作目录及报告路径。根据当次批准结果填写两个计划 ID。以下各段按顺序单独执行。初始化的功能小样已有 §7.1 的读回记录。

```bash
export DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home
approved_plan_id='填入获批的历史计划 ID'
# 算法换版时，按 §5.1 用 plan --replace-all 生成计划后再审批。
.venv/bin/python3 -B -m "$bootstrap_module" register --plan "$reviewed_plan" --plan-id "$approved_plan_id" --apply &&
  .venv/bin/python3 -B -m "$bootstrap_module" build --plan "$reviewed_plan" --plan-id "$approved_plan_id" --apply &&
  .venv/bin/python3 -B -m "$bootstrap_module" post-audit --plan "$reviewed_plan" --output "$reviewed_file_audit"
```

文件验收通过后生成事件计划。

```bash
.venv/bin/python3 -B -m "$bootstrap_module" events-plan --plan "$reviewed_plan" --file-audit "$reviewed_file_audit" --output "$reviewed_event_plan"
```

获批后先补录一个分区。样本日期必须在当次计划内，首次初始化可选 2010-01-04。该命令会读回核对该日产出及两项检查。

```bash
approved_event_plan_id='填入获批的事件计划 ID'
approved_event_sample_date='填入获批的样本交易日'
.venv/bin/python3 -B -m "$bootstrap_module" events-apply --plan "$reviewed_event_plan" --plan-id "$approved_event_plan_id" --trade-date "$approved_event_sample_date" --apply
```

样本通过且全量补录获批后执行。

```bash
.venv/bin/python3 -B -m "$bootstrap_module" events-apply --plan "$reviewed_event_plan" --plan-id "$approved_event_plan_id" --apply &&
  .venv/bin/python3 -B -m "$bootstrap_module" events-audit --plan "$reviewed_event_plan"
```

`events-apply --trade-date` 只处理一个获批样本日期，省略该参数则处理计划内所有待补录日期。所有写入命令绑定冻结的计划标识。正式执行与审批步骤遵守 [DG 执行规则](../../orchestrator/AGENTS.md)。

### 5.5 启用并验收日更

1. **先核对历史和日更之间的日期。** 取文件验收及事件对账通过的截止日 `D`，执行 §5.1 定义的 `read_structure_calendar "$history_through"`，其中 `history_through` 填已验收的 `D`。命令列出 `D` 之后已到 18:00 检查范围的 SSE 开市日，以及其中超出最近 10 个开市日的日期。在 [DG 控制台](http://127.0.0.1:3000) 的 **Assets → gold_major_index_quantitative_structure → Partitions** 核对这些日期。超窗且尚未完成的分区，按日期顺序用 §3.2 的同一个日更 Job 补跑。窗口内的待完成日期交给两个 Sensor 按顺序推进。尚无应处理日期时，等待 `D` 后首个 SSE 开市日。
2. **按顺序启用。** 在同一实例的 **Overview → Sensors** 找到 `orchestrator` 下的 `major_index_quantitative_structure_trade_day_sensor`，打开开关并确认是运行状态，再打开 `gold_major_index_quantitative_structure_update_job_sensor`。保持其他 Sensor 的当前状态。等待 daemon 自然检查，通过 Sensor 详情的 tick 记录查看分区登记、上游等待和提交结果。 [Dagster Sensor 操作](https://docs.dagster.io/guides/automate/sensors/monitoring-sensors-in-the-dagster-ui)
3. **验收首个自动日更。** 在日更 Sensor 详情确认首次提交日期是当前最早待完成日，打开其关联 Run，核对为 `gold_major_index_quantitative_structure_update_job`、分区日期正确且 Run 成功。在 Asset 分区页核对该日最新产出、`goldenshare/formula_version` 和两项指向同次产出的通过检查。只读打开该日产出对应的 Parquet，核对日期、一行、`success=true` 和事件数与产出记录一致。没有触发时先看 tick 的等待原因。运行失败时按 §3.2 重跑该日后复核。

将 `first_run_date` 设为首个自动 Run 的分区日期，按下列命令读回 Parquet。输出的第三项是事件数，应等于该日产出记录的 `goldenshare/event_count`。

```bash
first_run_date='填入首个自动 Run 的分区日期'
.venv/bin/python3 -IB - "$first_run_date" <<'PY'
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.duckdb_connection import DuckDBConnectionSettings, connect_configured_duckdb
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, gold_major_index_quantitative_structure_path

day = date.fromisoformat(sys.argv[1])
path = gold_major_index_quantitative_structure_path(Path(DEFAULT_LAKE_ROOT), day.isoformat())
with TemporaryDirectory(dir="/private/tmp") as temp:
    settings = DuckDBConnectionSettings(temp_directory=Path(temp))
    with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as connection:
        rows = connection.execute(
            "SELECT trade_date, success, len(results) FROM read_parquet(?, hive_partitioning=false)",
            [str(path)],
        ).fetchall()
    assert len(rows) == 1 and rows[0][:2] == (day, True) and rows[0][2] is not None, rows
print(rows[0])
PY
```

## 6. 可核算的执行量

| 单位 | 输入和写入 | 验收及恢复开销 |
| --- | --- | --- |
| 一次日更 | 从 2010-01-04 到目标日按月读入历史，计算器状态至多 45 组，写目标日一份结果 | 目标日候选读回一次。中断后重读相同历史范围，再写该日 |
| 一批 DuckDB 读取 | 按自然月组织，一个月最多 31 日，因此至多 279 份直接输入、5,022 根有效 K 线。批次消费完释放输入，结果按日校验和提升 | 每批核对最多 31 条逐日写入记录 |
| 估算历史全段 | 36,801 份输入、530,292 根 K 线、4,089 份结果文件和 4,089 行。现有输入物理文件共 253,652,591 字节 | 中断重跑从起点计算，只从未完成日开始写文件。结果写入时逐日读回，最终验收分批汇总最多 4,089 份结果文件。事件补录复用这份报告，上限 12,267 条，以已有事件差集为实际数量 |

SQL 连接使用现行 DG 配置，每次计算复用同一连接。日更日志按读取批次记录累计输入根数和耗时，历史初始化日志按日记录完成情况。计划阶段统计路径和物理大小，计算和输入核对使用同一批读取结果。没有 Tushare 或 Prod 请求。正式替换前核对候选占用和目标空间。超出批准的日期范围、发现应有输入缺失或检查失败时停止。 [现有 DuckDB 配置](../../orchestrator/src/orchestrator/defs/duckdb_connection.py)

### 6.1 开发前全历史读取与识别计时

用 2010-01-04 至 2026-11-06 的真实 DG 数据测一次。读 SSE 日历、`index_factor_pro`、四个周期的 `major_index_mins` 和 `major_index_mins_technical`，预期 4,089 个交易日、36,801 份行情与指标文件、530,292 根输入。文件的已统计总大小为 253,652,591 字节。只读测试使用 DG 现有解释器和 DuckDB 配置，临时脚本和 DuckDB 临时目录在 `/private/tmp`，禁用磁盘溢写。无需加载正式 Dagster instance。

沿用现有路径和完成时刻合同。DuckDB 按月读取所需列、对齐分钟价格和 MACD 并按时间排序。每月至多 279 份行情与指标文件和 5,022 根应有输入。核对本批返回的有效 K 线键后直接调用现有 r4.1，最多保留 45 个计算器的状态，只收集目标日的事件。计时分别记录日历及准备、DuckDB 查询到 Python 取得结果、输入根数与时间核对、r4.1 逐根识别及全程。缺失或重复时报告该月的键差异并停止。测试结果在内存中验收，读取和识别的耗时与正式 Parquet 写入、Dagster 记录耗时分别表述。

2026-11-09 实测一次，DG 环境 Python 3.13.5、DuckDB 1.5.2、4 线程、r4.1。203 个月共读取 36,801 份行情与指标 Parquet，另读 1 份日历。实际 530,292 根，所有月份的预期键和数量对齐。目标日输入 162 根，识别结果为空。峰值常驻内存为 2.13 GiB。

| 阶段 | 耗时 |
| --- | ---: |
| DuckDB 读取、对齐、排序并返回数据 | 7.27 秒 |
| r4.1 逐根识别 | 102.71 秒 |
| 日历、准备、输入核对和连接关闭等 | 1.35 秒 |
| **全程** | **111.33 秒** |

管理员已接受该实测开销，日更采用每日全量重算。111.33 秒和 2.13 GiB 对应截至 2026-11-06 的一次只读实测。正式 Parquet 写入与 DG 记录在实际作业中另计。相同历史范围的日更重跑重新承担这一次读取和识别开销。正式执行按获批日期和单批范围控制，写入前核对空间，数量不齐时停止。

## 7. 开发与验收

| 切片 | 验收条件 |
| --- | --- |
| A，共用内核 | 已完成。提交 `42acc9928`，财势乾坤现有回归与 DG 独立安装和计算验收已通过。正式 DG 依赖按第 2 节接入。Raw、Silver 不适用 |
| C2，Gold | 核对 r4.1 上证 90 分钟 11 月 4 日同根取消与新钝化顺序，以及后续结构事件。覆盖成功无事件、目标日前任一应有日缺输入、失败行、同一起点连续计算与中断重算一致。用总数相同但缺一个完成时刻且另一个时刻重复的分钟样本验证按键核对。另用含科创综指和北证50日线、科创综指分钟线的样本，确认额外代码不计入根数或结果 |
| D/E，入口和触发 | 用隔离 DG 的实际 definitions 和分区 job 验证两项检查归属，确认 job 只写本 Gold。覆盖 17:59:59 不检查、18:00:00 开始检查、休市日只补旧日期、已有产出但无检查不提交、人工提前运行跳过后仍可自动触发、计算失败行登记产出且完成检查标红。用同一 job 补跑一个已超出自动窗口的历史分区，验证只写目标日，且两项检查指向新产出。验证两条 sensor 的调用预算和已有分类规范 |
| F，正式前功能样本 | 用 `sample` 读取从 2010-01-04 起的首两个 SSE 交易日，在临时输出验证整日合同。重点对照上证日线和 90 分钟的来源、根数、事件及 Parquet 读回。空结果、失败状态和按日中断用隔离测试验证。按已确认要求省略小样耗时测试 |
| F，历史批量入口 | 用隔离文件和 DG instance 验证首次初始化写齐计划日期。换版验证截止日覆盖已有文件、按同一批量入口替换全部计划分区，并为每个日期登记新版产出和两项关联检查。重复补录时不新增已登记事件。正式初始化按第 5 节验收后启用日更 |

现有金样本固定结果来自 r4.1 回归记录，其中部分历史前缀用于构造已知参照。正式执行需把源端、对齐后根数、失败原因、结果行和事件数逐项对账。 [r4.1 金样本](../../../scripts/research/index_market/tests/test_xxm_r4_following.py) · [内核恢复测试](../../../scripts/research/index_market/tests/test_xxm_r4_restore.py)

### 7.1 开发验收记录

2026-11-09。DG 在临时环境使用已验收的共享包 wheel，加载完整定义。日更 job 只选择量化结构资产及两项阻断检查。隔离 DG 验证了上游未就绪、失败行、同日补跑、18:00 触发和 16 次状态接口调用上限。历史入口验证了中断后重跑、全量替换和重复补录。相关功能、运行合同、Catalog 和上游合同测试共通过 141 项。 [隔离测试](../../orchestrator/tests/test_major_index_quantitative_structure.py)

真实输入小样从正式 Lake 只读两日，写入和读回均使用临时目录。

| 交易日 | 日线根数 | 四个分钟周期对齐后的总根数 | 结果行数 | 事件数 |
| --- | ---: | ---: | ---: | ---: |
| 2010-01-04 | 6 | 85 | 1 | 0 |
| 2010-01-05 | 6 | 85 | 1 | 1 |

两日均为 `success=true`，读回字段及类型与 §3.1 一致。1 月 5 日的事件为中证500 30 分钟 14:30 的顶部钝化。正式 DG 安装、历史分区登记、全量写入、事件补录及 sensor 启用按第 5 节另行执行。

### 7.2 正式执行记录

2026-11-09。正式 DG 已加载共享包 `0.1.0` 和量化结构资产、日更 Job、动态分区及两项检查。历史文件阶段使用已批准的计划 `2818cfabfee59c93da14dbabaf56cca82c2df686606ddd2a12fd0f9d4a652ed8`，范围为 2010-01-04 至 2026-11-06，算法版本为 `xxm-direction-v0.5-r4.1`。

| 动作 | 实际结果 | 命令耗时 |
| --- | --- | ---: |
| `register` | 正式 DG 登记并读回 4,089 个交易日分区 | 1.56 秒 |
| `build` | 36,801 份行情及指标文件对齐为 530,292 根 K 线，写入 4,089 份 Gold 文件 | 118.39 秒 |
| `post-audit` | 实际文件日期与计划一致，每日一行且 `success=true`。读回共 33,666 个量化结构事件，其中 722 个交易日成功且无事件 | 1.47 秒 |

文件阶段验收通过。只读事件计划 `55894745f148f768faf43389948acb503fbef2131d58a35ae93aa6782b979508` 核对出待补录 4,089 条产出和 8,178 条检查，生成计划耗时 14.73 秒。

2026-11-09，按批准范围补录 2010-01-04 的一条产出和两条检查，命令耗时 1.38 秒。正式 DG 读回确认该日产出编号为 `7951532`，版本为 r4.1，输入 91 根 K 线，识别成功且无量化结构事件。结果合同检查和完成检查均通过，且都关联到该产出。

同日按同一计划补录剩余 4,088 条产出和 8,176 条检查，耗时 259.88 秒。全量对账耗时 16.42 秒，确认 4,089 个交易日均有与文件验收报告一致的 r4.1 产出，两项检查均通过并关联到对应产出。抽核首日及末日的产出编号分别为 `7951532` 和 `7963788`。历史初始化验收通过。

按上海时间 18:00 检查口径核对 SSE 日历，本次历史截止日之后无待补的旧交易日。2026-11-09 为开市日。

2026-11-09 上海时间 14:33，获批后依次启用分区登记 Sensor 和日更 Sensor，正式 DG 读回均为 `RUNNING`。两者首次自然检查均按 18:00 的约定跳过。

2026-11-10 上海时间 08:33，获批手动补跑 2026-11-09 分区。前一晚日更等待主要指数分钟线和主要指数分钟技术指标。上午九项上游产出及检查齐备后，用原日更 Job 执行，耗时 116.52 秒。产出编号为 `7971587`，算法为 r4.1，当日输入 162 根 K 线。正式文件读回一行，`success=true`，事件数为 0，与产出记录一致。结果合同检查和完成检查均通过，且都关联到该产出。 [本次补跑记录](http://127.0.0.1:3000/runs/caad0877-b84c-47a8-9a4c-fa21791e8235)

**待验收**。首个自动日更触发后，按 [§5.5](#55-启用并验收日更) 核对交易日、Job 结果、r4.1 产出、两项检查与当日 Gold 文件。

## 8. 财势乾坤接入详细设计

依据 [接入技术方案 §9](dagster-major-index-quantitative-structure-onboarding-plan-v1.md#9-财势乾坤接入技术方案)。本节定义 Gold 读取、结果与状态。页面入口、独立 API、缓存和调用方迁移按[普通与核验请求拆分 LLD](../../../wealth/docs/pages/index-detail/index-detail-debug-separation-low-level-design-v1.md)实施。上文的正式执行记录对应 DG 数据集。

2026-11-10，管理员确认财势乾坤本机真实页面验收通过。实现提交为 `260d18907`，自动测试、本机接口实测和人工确认分别见[财势乾坤验收记录](../../../wealth/docs/pages/index-detail/index-detail-debug-separation-low-level-design-v1.md#61-实施验收记录)。

### 8.1 修改位置和调用关系

| 位置 | 本次职责 |
| --- | --- |
| [日线接口](../../../src/biz/api/wealth/market/index_detail_xxm.py)和[分钟接口](../../../src/biz/api/wealth/market/index_detail_minute_xxm.py) | 沿用普通 `xxm-signals`、`minute-xxm-signals`、鉴权、`tsCode`、`period` 或 `freq`、`startDate`、`endDate`、`limit` 及 `Cache-Control: no-store`。显式 `debug` 参数按无效参数处理。两种地址沿用 [App 装配](../../../src/app/api/v1/router.py) 的本机环境和分钟能力门禁 |
| [识别查询服务](../../../src/biz/queries/wealth/market/index_detail_xxm/query_service.py) | 普通识别查询交易日历、主要指数量化结构文件和覆盖窗口的收盘价、MACD（12、26、9），返回事件、曲线点、覆盖范围及状态。核验地址和[预判入口](../../../src/biz/queries/wealth/market/index_detail_xxm/forecast_query_service.py)继续复用 `load_entry()` 及原计算 |
| [本机 Lake 读取层](../../../src/foundation/clients/local_lake/) | 增加 `major_index_quantitative_structure_reader.py`，根据传入的交易日列表批量读取结果。根目录取现有 `IndexDailyLakeReader.root`，正式文件相对路径为 `gold/indicator/major_index_quantitative_structure/trade_date=YYYY-MM-DD/part-000.parquet`。字段、九指数和有效起点按[方案 §2–3](dagster-major-index-quantitative-structure-onboarding-plan-v1.md#2-上游与历史起点)维护财势乾坤本地读取合同，部署时对照 DG 合同核验 |
| [API 响应类型](../../../src/biz/schemas/wealth/market/index_detail_xxm.py)及[前端响应校验](../../../wealth/src/features/index-detail/xxm/adapter.ts) | 普通与核验各自使用响应类型。普通页用识别回包的曲线点画量化结构副图，按 K 线完成时刻加事件。继续使用 `useIndexXxmLayer` 发出首批 K 线的请求 |
| [指数详情网页路由](../../../wealth/src/app/routes/WealthRouter.tsx) | 本机开发版且网址带 `debug=1` 时按需加载核验页。核验页首笔识别直接请求相应的 `/debug/` 地址。等待或加载失败时使用页面已有提示及重试 |
| [量化结构悬停](../../../wealth/src/features/index-detail/xxm/XxmLayerUi.tsx) | 普通页悬停展示当根时间及 Gold 事件。核验页使用原展示和详情组件 |

应用装配继续提供现有 Lake 读取依赖。读取层只访问本机正式 Parquet，使用已有 DuckDB 依赖。Biz 负责图表响应和状态，浏览器只访问财势乾坤 API。DG 依旧按既有 Job 和 Sensor 写入，事件读取不查询 DG 状态库。

### 8.2 单次请求怎么读取

1. 沿用 `require_xxm_code()`、现有参数验证和本机市场业务日期解析。按[方案 §2](dagster-major-index-quantitative-structure-onboarding-plan-v1.md#2-上游与历史起点)取该指数和周期的有效起点。范围下限取有效起点与 `startDate` 较晚者，上限取 `endDate` 和市场业务日期较早者，省略参数时使用有效起点或市场业务日期。用 `XxmLakeCalendar.recent()` 取截至上限最近 `ceil(limit/n) + 1` 个开市日，`n` 是该周期每个开市日的完成端点数，日线为 1。额外一日供截掉当前尚未完成的端点。日线以收盘完成为准，分钟沿用 `ENDPOINTS`。选日期范围内且不晚于请求时点的最近 `limit` 根应有端点，再按升序返回。
2. 以选中的端点日期生成分区文件清单。读取层用一次 DuckDB 查询读现有主要指数量化结构文件，使用 `hive_partitioning=false`，取物理 `trade_date`、`success` 和按 `ts_code`、`period` 筛选后的 `results`。用 `filename` 核对每份文件一行且物理日期与分区一致。按日升序处理，筛选后事件列表为空也保留该日，事件按列表原顺序。对缺文件按 §8.3 决定可用区间。
3. 按本次选中的完成端点筛选事件和计算覆盖范围。日线用 `trade_date`，分钟用交易日与上海本地 `bar_end_time`。同一交易日文件可包含本次范围以外的分钟事件，只返回本次范围内的事件。
4. 只为已覆盖的完成端点读取副图曲线。日线复用 `IndexDailyLakeReader.factor_rows()`，传覆盖日期清单和根数，从指数日线技术因子数据集（`silver/index/index_factor_pro`）读 `trade_date`、`close`、`macd_dif_bfq`、`macd_dea_bfq`、`macd_bfq`，上证日线同样走这一来源。分钟复用 [`read_minutes()`](../../../src/biz/queries/wealth/market/index_detail_xxm/source.py)，将 `MinuteSourceWindow.output_rows` 和 `read_rows` 都设为覆盖根数，首尾时间用覆盖区间的实际完成时刻。从主要指数分钟线数据集（`gold/quote/major_index_mins`）取 `close`，从主要指数分钟技术指标数据集（`gold/indicator/major_index_mins_technical`）取 `macd_dif`、`macd_dea` 和 `macd`，沿用按指数、频率、日期和完成时刻对齐及 `GOLD_PARAMS_KEY` 中的 MACD（12、26、9）合同。按升序返回覆盖窗口的曲线点。使用读到的时间与第 3 步选定的时间对齐，有缺口走 `XXM_SOURCE_CONTRACT_INVALID`。覆盖范围为空时跳过曲线读取。普通历史识别直接使用这批数据组装回包，无需读取用于计算的前序行情或调用识别内核。

### 8.3 返回字段、缺数据和页面行为

| 字段或情况 | 默认请求口径 |
| --- | --- |
| 标的、周期和版本 | `tsCode`、`period`、`algorithmVersion`、`specHash`。验收时核对 DG 已发布的 r4.1 版本，接口使用同版 `MAIN_SPEC` 的版本和规则摘要 |
| `points` | 每个已覆盖端点一项，按时间升序。字段为 `time`、`close`、`dif`、`dea`、`hist`、`ordinaryState`、`ordinaryDirection`。数值使用 §8.2 读到的收盘价及识别所用 MACD（12、26、9），两项状态字段固定为 `null`，悬停信息从当根事件取。时间格式与事件一致 |
| `events` | `event_type → type`、`direction → direction`、`display_on_chart → displayOnChart`。日线时间是 `YYYY-MM-DD`，分钟时间是 `YYYY-MM-DDTHH:MM:SS+08:00`。事件 ID 由指数、周期、完成时刻和同根事件在 Gold 中的顺序组成，顺序从 1 开始，包含不画标记的事件。同根 ID 在不同请求窗口中一致。图上只画 `displayOnChart=true` 的事件。默认悬停展示该根的事件列表，保持原顺序 |
| `meta` 和 `dataStatus` | `meta.count` 等于 `points.length`，`meta.responseStart` 和 `meta.responseEnd` 取曲线点首尾。即使一根 K 线没有事件，所在交易日成功时也计入覆盖。沿用 `dataStatus.status/message/asOf`，其中 `asOf` 取最后一个已覆盖端点 |
| 已成功，全部所选端点已覆盖 | `READY`。即使当根或整个窗口的事件列表为空，页面仍用 `points` 画曲线 |
| 窗口末尾尚无 Gold 文件，之前有成功结果 | `DELAYED`，只返回本窗口已覆盖的连续部分，提示结果截至哪根 K 线。后续请求重新读文件，以便看到 DG 新产出 |
| 窗口无可返回端点，或所选文件均未产出 | `EMPTY`，`points=[]`、`events=[]`、`meta.count=0`，`dataStatus.asOf` 及 `meta` 的首尾均为 `null`。后者的消息注明尚未生成结果 |
| `success=false` | 用既有 `XXM_QUERY_FAILED` 错误返回失败日期。页面沿用量化结构的错误和重试入口 |
| 窗口中间缺文件，或量化结构文件的物理日期与分区不符 | 用既有 `XXM_SOURCE_CONTRACT_INVALID` 错误返回缺口。中间缺文件指所选日期中缺文件的日期之后还有已产出日期 |

普通响应的顶层字段为 `tsCode`、`period`、`algorithmVersion`、`specHash`、`points`、`events`、`meta` 和 `dataStatus`。原 `source` 只随核验响应返回。

前端用 `points` 画量化结构副图的曲线和读数，按同一完成时刻加事件，标记高度用对应曲线点的 `dif`。按 `meta.responseStart` 到 `meta.responseEnd` 对齐已有 K 线和收盘价，区间外留空。普通 MACD 副图继续用 `/kline` 或 `/minute-indicators` 的结果，上证普通日线仍用 `/kline` 技术指标计算内核的结果。两副图的 MACD 数值各自取用，校验时只核对同根时间和收盘价。空结果使用接口消息区分尚未生成和暂无数据。研究核验继续使用原来的响应字段、前端检查和明细。

真实样本的事件字段示例为 `{"id":"000905.SH|m30|2010-01-05T14:30:00+08:00|1","time":"2010-01-05T14:30:00+08:00","type":"DULL","direction":"TOP","displayOnChart":true}`。ID 的四段按上述顺序用 `|` 连接。

首批 K 线和指标就绪后沿用 `useIndexXxmLayer` 的请求时机。开关只控制显示，向左续页只加载普通 K 线，量化结构复用首批窗口的响应。切回周期或页签沿用现有请求方式。晚间查看新结果时刷新页面，触发首批请求并重读 Gold。DG 从上海时间 18:00 起检查上游，财势乾坤默认业务日期按现有规则于 20:00 切换。若到 20:00 当日文件仍未生成，页面按本节的 `DELAYED` 或 `EMPTY` 显示。 [请求与复用](../../../wealth/src/features/index-detail/xxm/useIndexXxmLayer.ts) · [业务日期解析](../../../src/biz/queries/wealth/market/context/market_page_context_query.py)

### 8.4 性能和验收

普通识别每个选中的交易日最多读一份主要指数量化结构文件。覆盖成功的日期再读曲线数据，日线每天最多一份指数日线技术因子文件，分钟每天最多一份主要指数分钟线文件和一份主要指数分钟技术指标文件，只读所请求的频率。日线选 `limit` 根最多涉及 `limit` 个交易日。分钟每天有 `n` 根完成 K 线时，最多涉及 `ceil(limit/n) + 1` 个交易日，其中额外一天覆盖不足整日的分钟窗口。以 500 根为例，日线最多读 500 份量化结构文件和 500 份指数日线技术因子文件。90 分钟每天 3 根，三个数据集各最多 168 份，共 504 份。以上均另计 SSE 交易日历，属于文件数上限，实际耗时在本机验收。复用后端 2 个并发查询名额、4 秒请求和 1 MiB 响应预算，以及前端 5 秒请求超时。重试同一窗口使用相同读取上限。 [后端预算](../../../src/biz/services/wealth/market/index_detail_xxm/runtime.py) · [前端超时](../../../wealth/src/features/index-detail/xxm/apiClient.ts)

默认识别分支沿用 `time.perf_counter()` 和 `BUDGET.request_deadline_seconds` 的单次请求计时口径。用剩余时间等待现有 `_REQUEST_SLOTS`，每次打开 DuckDB 查询前从同一截止时间取剩余秒数。主要指数量化结构读取和现有分钟读取接受剩余秒数。日历与指数日线技术因子读取经 `IndexDailyLakeReader` 的 `calendar_rows()`、`factor_rows()` 将可选超时参数交给原 `_read()`，`XxmLakeCalendar` 在需要补读日历时取当时的剩余时间。已有调用按原默认值运行。DuckDB 中断沿用[分钟读取的做法](../../../src/foundation/clients/local_lake/major_index_mins_reader.py#L197)，超时抛给查询服务并映射为 HTTP 503 `XXM_BUDGET_EXCEEDED`，沿用提示「研究指标查询超时」。读取结束时关闭连接，在 `finally` 释放读取名额。响应组装和序列化仍核对同一截止时间和体积。页面超时、现有请求耗时统计与研究计算的计时方式沿用现行逻辑。

| 验收点 | 怎么验证 |
| --- | --- |
| 接口和范围 | 用独立样本覆盖日线和四个分钟周期、九指数范围、起点前、休市、分钟首尾截断和 `limit`。记录实际文件清单，验证普通识别只读交易日历、窗口内的主要指数量化结构文件及覆盖区间的曲线数据，识别内核调用次数为 0 |
| 事件和曲线 | 用同根两事件的固定样本验证次序、稳定 ID、画图标志和悬停。用真实 Gold 核对 2010-01-04 成功无事件、2010-01-05 中证500 30 分钟 14:30 顶钝化。用上证日线、其他指数日线及 90 分钟对照 §8.2 的曲线来源。用普通 MACD 与识别值不同的样本核对两副图各用各的值。上证日线可用 [2024-09-24 的已验收样本](../../../wealth/docs/system/detail-chart-quantitative-structure-requirements-v1.md#1-目标与现状)对照回包和绘图输入的原始值，标记高度须取识别点的 DIF |
| 请求与更新 | 验证首批就绪发请求，开关副图和历史续页不追加识别请求。覆盖 20:00 前后的默认业务日期，补齐文件后刷新页面可见新结果 |
| 等待与失败 | 验证成功空事件、末尾尚未产出、全窗口无产出、明确失败、窗口中间缺文件。超时用例验证 503 和错误码，再发一笔能成功的请求确认名额已释放。错误提示限于量化结构 |
| 研究核验与预判 | 延迟加载核验代码时，验证第一笔识别直接走 `/debug/xxm-signals` 或 `/debug/minute-xxm-signals`。核验请求沿用原计算、原字段和参照详情。普通识别与核验识别分别对照 Gold 固定样本和既有核验样本。下一根预判核对两种地址对同一输入的公开结论 |
| 本机验收 | 跑识别接口、路由门禁、预判和前端响应与悬停回归。使用真实 API 打开指数详情页，核对日线和分钟图显示、普通 MACD 同屏及首批请求范围，记录冷、热请求实际耗时与打开的文件数 |

现有[页面请求验收脚本](../../../scripts/research/index_market/xxm_page_request_audit.py)继续统计 HTTP、浏览器耗时和响应体积。默认识别从实际响应核对 `dataStatus`、`meta`、`points` 和 `events`，其中脚本的 `computedThrough` 取 `dataStatus.asOf`，`responseRows` 记录 `meta.count` 的覆盖端点数。所读文件和识别调用次数由真实路由测试记录。`prefixRows`、`sourceInputId` 对默认识别留空。默认识别分别对照 Gold 事件和识别使用的 MACD；核验和预判继续检查原计算、计算前缀与来源标识。

先完成隔离测试，再用有限日期做正式 Lake 只读核验和本机页面验收。切换失败时按现有发布方式恢复前一版财势乾坤，修正后重验本节用例。

### 8.5 编码门禁矩阵

现有[量化结构页面需求](../../../wealth/docs/system/detail-chart-quantitative-structure-requirements-v1.md)是图表基线，新增读取和悬停口径以方案 §9 和本节为准。下表对照[财势乾坤通用清单](../../../wealth/docs/system/module-delivery-checklist-v1.md)。例外白名单为空。

| 清单 | 适用性与落点 | 验证 |
| --- | --- | --- |
| §2.1 交付事实链 | 适用。既有页面需求、方案 §9 和 LLD §8 | 开工前评审默认响应及核验请求的范围 |
| §2.2 后端事实归一 | 适用。§8.2–8.3 分别定义量化结构曲线和 Gold 事件的来源 | 对照真实 Gold 事件及日线、分钟识别所用的 MACD（12、26、9） |
| §2.3 状态 | 适用。§8.3–8.4 定义加载、正常、空、滞后、失败、超时 | 覆盖等待后成功、超时后可重试及所显示的消息 |
| §2.4 显示与语义 | 适用。§8.3 按事件类型、方向和画图标志展示 | 核对同根事件顺序、标记与悬停 |
| §2.5 行为过程 | 适用。§8.3–8.4 规定首次请求、开关、续页和刷新 | 浏览器核对请求、等待和刷新。布局变体沿用已验收的副图 |
| §2.6 文档同轮同步 | 适用。以两份原文档、响应示例和测试对账 | 检查最终接口和页面行为与设计一致 |
| §2.7 替换范围与恢复 | 适用。§8.1、§8.4 记录接入和回滚。mock/real 开关项不适用，两侧均是真实数据 | 对照发布版本和默认识别读 Gold 的接口用例 |
| §2.8 契约与消费者 | 适用。§8.3 定义字段、可空策略、状态和示例 | 路由响应、前端解析及真实展示用例 |
| §2.9 坐标及文案 | 适用。图上时间与量化结构 DIF 对齐。计数型固定刻度不适用，DIF 可正可负 | 核对事件落在对应时间和 DIF，检查正负值及缺值 |
| §2.10 计算与传输 | 适用。§8.2、§8.4 按窗口读取和筛选事件。聚合统计兼容项不适用，本次是已有事件读取 | 对账文件数、识别调用次数及端到端实测 |
| §2.11 策略配置 | 不适用。使用现有本机 Lake 根和分钟能力 | 回归本机、生产环境路由门禁 |
| §2.12 清单映射 | 适用。本表及下表 | 开工前评审 |
| §2.13 例外与语义断言 | 适用。事件与坐标由 §8.3、§8.4 约束 | 用例验证零值、缺值及同根事件顺序 |
| §2.14 显式坐标参数 | 不适用。本次换识别来源，沿用现有副图渲染参数 | 页面核对同一事件落在其 DIF 位置 |
| §2.15 并排双图 | 不适用。普通 MACD 与量化结构为上下副图 | 真实页面核对同屏各自读数 |
| §2.16 指标卡片文案 | 不适用。改动限于量化结构副图状态和悬停 | 真实页面检查悬停事件和状态文案 |
| §2.17 真实 API 与展示 | 适用。§8.4 和下方核心用例 | 按下方命令和页面步骤记录结果 |
| §2.18 八项原则 | 适用。逐项对应如下 | 核对落点和验收记录 |

| §2.18 原则 | 落点与验收 |
| --- | --- |
| 单一事实源 | §8.2–8.3。页面用量化结构回包的 `points` 画曲线，用 Gold 事件画标记；普通 MACD 用现有图表接口 |
| 契约先行 | §8.3。真实响应断言普通字段集合和核验原有字段 |
| 配置一致 | §8.1。用现有本机 Lake 配置，回归环境和权限 |
| 默认行为 | §8.1、§8.3。首批识别、刷新、缺结果和核验页首笔请求地址均有用例 |
| 筛选和顺序 | §8.2–8.3。核对九指数、周期、完成端点和同根事件顺序 |
| 性能预算 | §8.4。实际读文件数、后端 4 秒和前端 5 秒按真实请求验收 |
| 可观测和异常 | §8.3–8.4。沿用耗时统计和错误码，分别核对 Gold 读取与原计算路径 |
| 用户可见结果 | §8.4。真实 API 驱动页面，核对曲线、标记、悬停、等待和错误 |

核心用例的普通识别字段为 `points`、`events.id/time/type/direction/displayOnChart`、`meta`、`dataStatus` 和错误响应的 `code/message`。量化结构的 DIF、DEA 和 MACD 按 §8.2 的来源核对。本机浏览器打开指数详情页，核对两副图各自的曲线和读数，以及量化结构标记和悬停，检查开关和刷新前后的网络请求，并按 §8.4 记录文件数和耗时。

```bash
python -m pytest -q tests/test_index_daily_lake_reader.py \
  tests/web/test_wealth_index_detail_xxm_api.py \
  tests/web/test_wealth_index_detail_xxm_local_routes.py \
  tests/web/test_wealth_index_detail_xxm_forecast_api.py \
  scripts/research/index_market/tests/test_xxm_p4_audit_tools.py
npm --prefix wealth run test -- src/pages/index-detail/IndexDetailPage.test.tsx src/features/index-detail/xxm src/features/index-detail/debug
npm --prefix wealth run typecheck
npm --prefix wealth run test
npm --prefix wealth run build
```
