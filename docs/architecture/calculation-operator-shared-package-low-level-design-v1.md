# 计算算子共享包 LLD v1

2026-11-09 · 共享包 `0.1.0` 已完成源码迁移和本地验收。对应 [落地方案](calculation-operator-shared-package-plan-v1.md)及[实现与验收记录](#8-实现与验收记录)。

## 1. 源码与交付目录

发行包名为 `goldenshare-technical-indicators`，导入名为 `goldenshare_technical_indicators`，首个包版本为 `0.1.0`。包版本用于安装。`KERNEL_VERSION`、各 `CalculationDefinition.algorithm_version`、`MAIN_SPEC.algorithm_version` 与预判版本仍分别由原定义维护。首轮验收使用两个工程当前的 Python 3.13 环境，共享包的 `requires-python` 为 `>=3.13`。

```text
packages/technical_indicators/
  pyproject.toml
  src/goldenshare_technical_indicators/
    contracts.py, service.py, executor.py, errors.py, execution_control.py, time_range.py
    calculation/           # 现有引擎、注册表、算子和 SQL
    configuration/         # 现有 KernelConfig 数据对象及校验
    sources/               # 现有输入合同、批次、复权、SQL 与行转换
    output/                # 现有结果合同、组装、编码和 SQL
    discovery/             # 现有能力说明
    xxm/
      __init__.py
      calculator.py
      snapshot_validation.py
      spec.py
      types.py
      event_display.py
```

沿用现有 Setuptools 构建方式。新项目发现 `src/` 下的独立导入名，并为 `calculation`、`sources`、`output` 明确登记 `sql/*.sql`。迁移前的目录含 35 份 Python 文件和 14 份 SQL 文件。SQL 分别是 9 份计算、3 份输入、2 份输出，构建后核对名称和内容与原文件一致。根 `pyproject.toml` 删除原内核的三条资源登记，保留其他包和资源设置。 [现有主工程打包配置](../../pyproject.toml#L45) · [Setuptools 的包内文件规则](https://setuptools.pypa.io/en/latest/userguide/datafiles.html)

基础包允许只运行 r4.1、导入配置和读取算子说明。DuckDB 计算仍在实际调用时加载 DuckDB，`IndexDailyPriceSource` 在组装批次时加载 PyArrow。对独立的通用指标调用方拟提供 `sql` 安装选项，使用主工程现有的 `duckdb>=1.3,<2`、`pyarrow==23.0.1`。财势乾坤现有 `local-lake` 依赖及运行版本沿用原口径，DG 的 r4.1 验收只安装基础包。首轮以两边已装版本为实测范围。 [DuckDB 连接](../../packages/technical_indicators/src/goldenshare_technical_indicators/service.py#L29) · [日线批次转换](../../packages/technical_indicators/src/goldenshare_technical_indicators/sources/index_daily.py#L30) · [现有依赖](../../pyproject.toml#L30)

## 2. 技术指标代码迁移

| 现有代码 | 迁移动作 | 必须保持的行为 |
| --- | --- | --- |
| `contracts.py`、`time_range.py`、`errors.py`、`execution_control.py`、`executor.py`、`service.py` | 随目录迁移。已有相对引用及服务入口按原方式工作 | 请求归一化、默认及硬上限 500 根、失败类型、私有内存 DuckDB、超时取消和清理顺序 |
| `calculation/` | 整体迁移。同步 `sql_templates.py` 中的包名与白名单键、`engine.py` 中的包名判断，以及 `indicators/` 中 `SQL_PACKAGE` 的值 | 白名单文件集、模板正文、指标注册和计算顺序、参数和预热、首根初始化、复权与计算批次间的状态 |
| `sources/` | 整体迁移，更新 `read_context.py` 的 `SQL_PACKAGE`。`IndexDailyPriceSource` 仍用调用方给出的行和回读函数，按原合同组装批次 | 日期语义、批次边界、复权路径、预热数据与当前页行的关系。实际数据库和 Lake 读取入口由财势乾坤保留 |
| `output/` 与 `discovery/` | 整体迁移。更新 `collector.py` 中的 `_OUTPUT_PACKAGE`。通用结果和编码留在包内，API DTO 和发送留在调用方 | 列顺序、空值、空结果、字节预算、结果收集与释放顺序，能力说明的公开字段和版本 |
| `configuration/settings.py` | `KernelConfig` 的字段、类型和校验迁入包。现有 `from_settings` 的字段复制移至主工程 `src/foundation/config/settings.py` 的 `technical_indicator_config_from_settings(settings)`。该文件的 `_MAX_OUTPUT_ROWS` 引用改到共享包 | `GOLDENSHARE_LAKE_ROOT` 和现有 18 个 `TECHNICAL_INDICATOR_*` 字段仍由同一 `Settings` 解析。默认值、别名、校验、生效方式、可见性及资源限制均按原定义 |

`SQL_PACKAGE` 的改动覆盖 `calculation/engine.py`、`calculation/sql_templates.py`、`calculation/indicators/{price,moving_average,bollinger_bands,macd,kdj}.py`、`sources/read_context.py` 和 `output/collector.py`。只替换包名前缀，同步相关测试中的固定资源名。用 `git diff -M` 核对迁移的 Python 文件，只接受本表和第 3 节明确列出的改动。逐文件比对 SQL 内容，保留原来的模板检查。 [模板装载](../../packages/technical_indicators/src/goldenshare_technical_indicators/calculation/sql_templates.py#L13) · [配置复制](../../src/foundation/config/settings.py#L153) · [现有配置项](../../src/foundation/config/settings.py#L68)

## 3. r4.1 代码迁移

原目录为 `src/biz/services/wealth/market/index_detail_xxm/`。迁移按下表执行。

| 文件或符号 | 新位置与引用 | 验收重点 |
| --- | --- | --- |
| `calculator.py`、`spec.py`、`snapshot_validation.py` | 移到共享包 `xxm/` 的同名模块。更新 `XxmCalculator`、`MAIN_SPEC`、`validate_structure_record`、`validate_structure_facts` 及测试引用 | `step()`、`snapshot()`、`restore()` 和 `record_decisions` 行为一致。事件 ID、`spec_hash`、结构记录、恢复拒绝规则与错误后状态一致 |
| `types.py` 的识别部分 | 将 `XxmPeriod`、`XxmBar`、`Wave`、`XxmStructureRecord`、`XxmReferenceFacts`、`XxmWaveFacts`、`XxmDecision` 及其组成类型、`XxmStep` 移到 `xxm/types.py` | `XxmBar` 和 `XxmSpec` 各只有一份类型定义。历史输入、预判构造的假设 K 线、恢复代码和 DTO 校验使用同一类型 |
| `types.py` 的预判部分 | 原处保留 `ForecastPrecheck`、`ComparisonRanges`、`ForecastConditionDraft`、`ReferenceForecast`、`StructureFollowConditionDraft`、`ForecastKernelResult`，从共享包引入所需的识别类型 | `Interval` 及预判类型继续由原模块维护。预判的结构引用、候选区间和文案保持原样 |
| `response_projection.py` 的 `event_display_flags` | 原函数体移到 `xxm/event_display.py`。现有响应组装和调试校验从新位置调用 | 同一指数同一周期的事件顺序、全部事件和 `displayOnChart` 保持原样。普通响应与调试响应的 DTO、字段和校验留在财势乾坤 |

预判仍由财势乾坤的 `forecast*.py`、`projection.py` 计算。`forecast_detector.clone()` 从共享包创建计算器再恢复状态，现有预判调用的计算器方法和属性沿用原实现。版本、事件 ID 和状态内容来自原数据字段及计算逻辑，迁移时不改变 `sourceIdentity`、字典键、时间格式及运算顺序。现有查询缓存依旧在进程内，状态恢复用原字典格式验收。 [识别状态与事件 ID](../../packages/technical_indicators/src/goldenshare_technical_indicators/xxm/calculator.py#L51) · [状态保存与恢复](../../packages/technical_indicators/src/goldenshare_technical_indicators/xxm/calculator.py#L584) · [预判复制计算器](../../src/biz/services/wealth/market/index_detail_xxm/forecast_detector.py#L38) · [类型定义](../../packages/technical_indicators/src/goldenshare_technical_indicators/xxm/types.py) · [图上标记函数](../../packages/technical_indicators/src/goldenshare_technical_indicators/xxm/event_display.py#L4)

## 4. 现有调用方逐项切换

| 消费位置 | 已核对的引用及实施动作 |
| --- | --- |
| `src/foundation/config/settings.py` | 启动导入 `_MAX_OUTPUT_ROWS`，由新包提供同一个常量。保留全部默认和环境变量定义。配置复制见第 2 节 |
| `src/foundation/clients/local_lake/technical_indicator_{contracts,price_locator,price_source}.py` | 切换 `KernelConfig`、`PriceSource` 相关类型、`SqlStep` 和错误类型引用。Parquet 路径、Arrow 读取、取数上限及股票复权行为沿用原实现 |
| `src/app/runtime/technical_indicators/{composition,admission,execution,response}.py` | 配置由主工程函数生成，注册表、控制、结果及错误类型从共享包引用。并发、取消、编码和响应释放继续在原模块 |
| `src/app/dependencies/{stock_daily_technical_indicators,index_daily_technical_indicators}.py` | 股票仍从原查询得到行情来源，指数仍复用主图价格和此前交易日。切换服务及类型引用，保留现有调用 `calculate` 与 `_prepare_calculation`、`_calculate_result` 的各自路径 |
| `src/biz/services/wealth/market/stock_detail/stock_daily_kline_{calculations,service}.py`、`src/biz/queries/wealth/market/index_detail/index_detail_kline_query_service.py` | 切换计算请求、结果及错误类型引用。保留各自指标清单、数量和 DTO 字段映射 |
| `src/biz/queries/wealth/market/index_detail_xxm/{query_service,forecast_query_service,source}.py` | 历史识别、预判、行情转换改引共享计算器、版本及输入输出类型。查询窗口、行情选择、时间对齐、缓存与恢复的调用顺序沿用原行为 |
| `src/biz/schemas/wealth/market/index_detail_xxm{,_forecast}.py` | 切换 `MAIN_SPEC`、`XxmBar`、结构校验与 `event_display_flags` 的引用，含函数内部的延迟导入。保留现有普通、调试和预判响应合同 |
| `src/biz/services/wealth/market/index_detail_xxm/{forecast,forecast_detector,projection,response_projection,types}.py` | 按第 3 节切换识别符号。其余 `forecast*` 模块继续使用本地预判类型 |
| 诊断与研究 | `scripts/diagnostics/technical_indicator_{d2_acceptance,resources}.py` 切换通用包引用。`scripts/research/index_market/xxm_page_request_audit.py` 和 `xxm/` 的 `acceptance.py`、`daily_window_precheck.py`、`history_disappearance_screen.py` 等已命中的活跃脚本切换识别引用，保留研究入口与用例 |
| 测试与静态检查 | 覆盖 `tests/foundation/technical_indicators/`、`tests/app/technical_indicators/`、`tests/architecture/test_technical_indicator_dependencies.py`、`tests/test_stock_daily_kline_service.py`、`tests/stock_daily_kline_helpers.py`、`tests/web/` 的 XXM 用例和 `scripts/research/index_market/tests/`。同步 mock 目标、断言的资源名以及测试脚本中的字面导入。预期业务结果沿用原用例 |

用 CodeGraph 核对了 `TechnicalIndicatorService`、`CalculationEngine`、`PriceSource`、`IndexDailyPriceSource`，以及 `XxmCalculator`、恢复校验、响应和预判入口。再用源码搜索补查配置、包名字符串、函数内导入、测试补丁与诊断脚本。当前 DG 代码没有直接导入这两套内核。迁移提交前对 `src`、`qtf`、`scripts`、`tests`、DG 源码和安装配置重跑引用清单。旧内核包名、被迁移的 r4.1 模块路径和 `KernelConfig.from_settings` 在活跃代码中归零。测试中的明确反例和历史文档按原证据保留。 [Web 装配](../../src/app/runtime/technical_indicators/composition.py#L31) · [股票调用](../../src/app/dependencies/stock_daily_technical_indicators.py#L167) · [指数调用](../../src/app/dependencies/index_daily_technical_indicators.py#L28) · [现有资源与依赖静态检查](../../tests/architecture/test_technical_indicator_dependencies.py)

## 5. 构建、安装和交付

| 入口 | 设计与影响 |
| --- | --- |
| 同仓开发与根锁文件 | 根 `pyproject.toml` 声明 `goldenshare-technical-indicators==0.1.0` 为基础依赖，因为 `Settings` 和 r4.1 都在基础入口使用它。在 `[tool.uv.sources]` 用相对路径 `packages/technical_indicators` 解析同仓开发依赖。更新根 `uv.lock` 的本地依赖项，核对已有第三方依赖版本。导出的发行元数据只引用包名和版本 |
| 主工程本地启动脚本 | `scripts/local-build-and-run.sh` 仅在现有 `--install-python-deps` 分支，同一次 pip 安装显式提供共享包与主工程两个本地 editable 路径。帮助说明与实际安装同步。原后端编译检查补入 `packages/technical_indicators/src`，保留原入口、参数和跳过规则。普通启动使用已准备的依赖环境。保留该脚本现有工作区改动 |
| 发版预检 | `scripts/release-preflight.sh` 在现有 `RUN_COMPILE_CHECK` 分支将 `packages/technical_indicators/src` 加入编译目标，保留原命令、开关和其他步骤 |
| CI | 在 `.github/workflows/ingestion-guardrail.yml` 的 `pull_request` 和 `push` 路径条件中加入 `packages/technical_indicators/**`。沿用现有事件和分支条件。CI 在自己的环境里构建共享包，并把产物作为现有 `pip install -e .[dev]` 的附加输入，验证新环境可以首次安装 |
| 本地 wheel 交付 | 获准发布且包内容有变化时，更新包版本和主工程依赖声明，从审核后的同一提交构建一份 wheel。包内容及目标版本一致时复用已验收的 wheel 和安装。构建源和产物放在 `/private/tmp` 的本次执行目录，记录源码提交、包版本、文件清单、SHA-256。财势乾坤和 DG 的交付用同一份 wheel。安装后从仓库目录外验证实际导入位置和包版本 |
| 现有生产安装入口 | `deploy-layered-systemd.sh` 在拉取代码后运行 `.venv/bin/pip install -e`，现有服务使用可编辑安装的源码。隔离环境先验证首次安装与从旧版本升级。获准发布后，在切换源码前先核对 wheel 的 SHA-256，用目标解释器预装符合主工程依赖声明的版本并确认能导入。随后原样执行 `bash scripts/deploy-systemd.sh dev-interface`，依赖安装使用已装好的版本 |
| DG | 用现有 DG 的 Python 3.13.5 在临时独立环境安装基础 wheel，验证 r4.1。DG 的 `pyproject.toml`、`uv.lock`、`dg dev` 和现有定义仍按当前工程管理。DG 声明 `>=3.10,<3.15`，而共享包初版按 `>=3.13` 交付。接正式消费者时须在其方案中明确适用解释器和依赖声明，避免连带改变 DG 其他任务的 Python 支持范围 |

开工审计已用本机现有的 Python 3.13.5、Setuptools 78.1.1、wheel 0.45.1 和 pip 25.1 离线构建一个带 SQL 文件的临时小包，核对 SQL 已装入 wheel。正式构建用这套工具，实施前复核版本。管理员已同意后续验收时仅将本需求的 wheel 安装到 `/private/tmp` 下的隔离环境。通用指标复用主工程已装的 DuckDB 和 PyArrow，DG 继续使用自己的解释器。预装失败时先解决依赖问题再切换源码，切换后的验收失败时按既有发布流程恢复原源码和对应依赖，再重新验收。 [uv 本地依赖规则](https://docs.astral.sh/uv/concepts/projects/dependencies/#path) · [pip 安装规则](https://pip.pypa.io/en/stable/cli/pip_install/#overview) · [本地安装入口](../../scripts/local-build-and-run.sh#L240) · [编译预检入口](../../scripts/release-preflight.sh#L37) · [生产安装入口](../../scripts/deploy-layered-systemd.sh#L368) · [CI 安装入口](../../.github/workflows/ingestion-guardrail.yml#L70) · [DG 支持范围](../../lake_console/orchestrator/pyproject.toml#L1)

隔离构建和 r4.1 安装验收使用以下命令。`run_dir` 是 `/private/tmp` 下本轮目录，`build-src` 是审核后的包源码副本，`build_python` 是已具备构建工具的解释器，`dg_python` 指向 DG 现有解释器。`wheel` 填本轮实际生成并已核对 SHA-256 的文件。

```bash
"$build_python" -m pip wheel --no-index --no-deps --no-build-isolation \
  --wheel-dir "$run_dir/wheels" "$run_dir/build-src"
uv venv --offline --no-python-downloads --python "$dg_python" "$run_dir/dg-smoke"
uv pip install --offline --no-deps --python "$run_dir/dg-smoke/bin/python" "$wheel"
```

从 `run_dir` 用隔离环境的 `python -I -B` 执行现有 r4.1 固定案例。通用指标的安装验收同样从仓库目录外运行，使用实际获准的 DuckDB 和 PyArrow 依赖。核对 wheel 内文件和发行元数据，确认运行时导入的是安装产物。

## 6. 迁移前后对照验收

先在迁移前记录代码提交、Python、DuckDB、PyArrow 版本和输入样本。两次对照使用同一组依赖和输入，记录输出及失败原因。已有字面预期、独立计算参考、已确认研究案例和既有夹具继续作为验收依据。

| 验收项 | 对照内容及现有用例 |
| --- | --- |
| 通用指标数值和时间范围 | 运行 `test_price_adjustment.py`、`test_source_contracts.py`、`test_request_reuse_correction.py` 及指数日线集成用例。核对价格、MA、BOLL、MACD、KDJ 的参数、输出顺序、数值、空值、初始化与预热、日线和已有周期的时间合同。已结案的字面数值用例用作安装验收的输入和预期来源 |
| 请求、配置和失败 | 运行 `test_contracts.py`、`test_configuration.py`、`test_errors_and_cleanup.py` 和 `test_request_reuse_correction.py`。指数日线集成用例覆盖空页。核对 500 根硬上限、现有 18 项配置、空结果、来源错误、取消和请求释放 |
| 股票与指数日线 API | 复用 `tests/app/technical_indicators/test_stock_daily_integration.py`、`test_index_daily_kline_integration.py`、`test_execution_cancellation.py`、`test_response_lifecycle.py`。使用已有合同夹具和现有入口，核对参数、HTTP 状态与响应字段、标记值、回读价格和清理。正式来源验证使用已有获准留样或另获准的最小只读范围 |
| r4.1 结果 | 复用 `scripts/research/index_market/tests/test_xxm_r4_following.py`、`test_xxm_r4_restore.py`、`test_xxm_snapshot_validation.py`、`test_xxm_confirmed_cases.py`。核对已确认的上证 90 分钟案例、日线和各分钟周期、同根事件顺序、事件 ID、结构变化、同根图上标记、跨时段连续与恢复、错误输入和原状态保留。版本、哈希和快照字典逐项相同 |
| r4.1 现有 Web 调用 | 复用 `tests/web/test_wealth_index_detail_xxm_api.py`、`test_wealth_index_detail_xxm_forecast_api.py`、`test_wealth_index_detail_xxm_forecast_validation.py`、`test_xxm_shared_loads.py` 和研究侧预判用例。对照普通与调试响应、现有来源标签、缓存复用、预测区间和失败结果 |
| 安装产物 | 在仓库目录外，以安装产物的解释器加载模块并核对真实路径、发行版本和 wheel 哈希。用原字面用例的三根不复权日线，收盘价依次为 10、12、11，按原参数和预期核对价格、MA、BOLL、MACD、KDJ，实际执行输入、计算和输出 SQL。DG Python 隔离环境执行现有 r4.1 固定案例，并核对跨一处状态保存点的结果。还要验证基础安装可导入主工程 `Settings`，仅用共享基础包可运行 r4.1 |
| 静态与交付入口 | 更新原有 `test_technical_indicator_dependencies.py` 的源码根、独立包资源和禁止依赖检查。先断言新源码根和两个计算入口实际存在，再扫描禁止依赖。核对 14 份 SQL 装入 wheel、内容相同、旧导入清零。验证本地显式安装、两个编译入口的目标与原跳过开关、CI 首次安装、预装 wheel 后原发布命令的依赖解析以及版本不匹配的失败行为 |

本轮验收使用现有有界测试或经批准的最小只读样本，正式数据写入、任务触发和全历史回放均为零。运行范围以评审后的测试清单为准。已有请求上限、线程和内存约束以现有配置及各用例为依据。构建、安装、对照和最终检查的时间与内存记录实测值，发现超出既有门槛或出现结果差异时停在本步骤。测试中断时从失败组重跑，记录各组使用的同一源码和 wheel，避免把之前版本的通过结论混入。相关测试若已有专用受保护入口，按其现有授权与运行方式执行。 [通用数值用例](../../tests/foundation/technical_indicators/test_indicator_literals.py) · [指数日线回归](../../tests/app/technical_indicators/test_index_daily_kline_integration.py) · [r4.1 固定用例](../../scripts/research/index_market/tests/test_xxm_r4_following.py#L39) · [恢复回归](../../scripts/research/index_market/tests/test_xxm_r4_restore.py)

设计审计期间在 `09409ed6d` 的现有内核上运行了 6 项有界检查，全部通过。包含依赖与资源的 4 项现有静态检查、上证 90 分钟固定案例和 r4.1 无文件及网络访问的用例。这些结果仅作为迁移前证据。 [静态检查](../../tests/architecture/test_technical_indicator_dependencies.py) · [r4.1 用例](../../scripts/research/index_market/tests/test_xxm_r4_following.py)

### 6.1 迁移前的测试修正

在 `79afb28c0` 上的两批有界回归共 1,744 项通过、8 项失败。CodeGraph 与现行代码确认调用位置，临时副本和本地 Parquet 小样验证了下表的修正。只改表中的测试和本需求的文档，业务代码、配置、安装脚本和数据集开发留待后续步骤。

| 测试文件 | 修正及验收 |
| --- | --- |
| `tests/app/technical_indicators/test_stock_daily_integration.py` | 在 `_calculate_library` 和 `_calculate_result` 替换计算，实际执行队前准备，并核对它传入的是原请求。继续检查响应、拒绝无效请求、库返回类型、取消和资源释放 |
| `tests/foundation/technical_indicators/test_price_adjustment.py` | 在第二批检查前一批的复权价格，末批检查临时历史表已释放。周月线使用临时 Parquet 走实际定位器，覆盖期中可用、仅有晚于截止日的版本应拒绝、已收盘周期可用三种情况 |
| `tests/foundation/technical_indicators/test_errors_and_cleanup.py` | 分钟流跳过空分区，核对只打开有数据的两个文件，仍验证读入 10,000 根后取消时释放待交付的 1,808 根 |
| `tests/foundation/technical_indicators/test_source_contracts.py` | 在定位器打开文件元数据后发出取消，核对只访问首个文件且返回取消错误。保留原文件数量上限断言 |

复跑审计的两批测试。第一批为架构依赖检查、Foundation 的配置、合同和请求复用用例，App 的指数和股票日线集成，以及 r4.1 的连续识别和恢复。第二批为 Foundation 的复权、错误清理和来源合同，App 的取消和响应生命周期，XXM 的 Web 历史、预判、预判校验、共享加载，以及研究侧的状态校验和已确认案例。按上述文件清单分两次运行，使用 `/private/tmp` 下的独立 pytest 目录。旧 D2 四批次用例依赖已不存在的诊断文件，本轮用同模块现有临时夹具的跨文件合批用例覆盖，历史用例原样保留。绑定已结案 D3 计划的用例仅引用输入和预期，沿用指数日线集成用例验证空页。 [D2 固定夹具用例](../../tests/foundation/technical_indicators/test_source_contracts.py#L539) · [D3 夹具入口](../../tests/foundation/technical_indicators/d3_support.py#L399) · [指数空页测试](../../tests/app/technical_indicators/test_index_daily_kline_integration.py#L131)

两批在开工审计时的 pytest 实测用时分别为 9.93 秒和 44.63 秒。若中断，从该批起重新运行，完整重跑仍为这两批，再做文档完整性、链接和提交范围检查。数据来源仅使用现有回归样本、临时 Parquet 和隔离数据库。全通过后记录实际结果并单独提交，停止在源码迁移之前。

2026-11-09 修正后复跑。主工程使用 Python 3.13.5、DuckDB 1.5.5、PyArrow 23.0.1。第一批 901 项通过，pytest 用时 9.59 秒。第二批 851 项通过，pytest 用时 44.30 秒，未选入上文的 1 项 D2 诊断用例。合计 1,752 项通过，8 项原失败全部通过。DG 环境已核对为 Python 3.13.5、DuckDB 1.5.2，实际安装验收留待迁移阶段。

## 7. 交接

共享包 `0.1.0` 已通过两套环境的独立安装验收和财势乾坤的迁移前后对照。量化结构数据集接入时，使用本 LLD 定义的共享包路径及 `goldenshare_technical_indicators.xxm`，同时修正数据集 LLD 中原先单独打包 r4.1 的路径。

新增指标时在共享包登记该指标需要的输入、参数、输出、算法版本及独立预期。现有通用 SQL 算子沿用已有注册方式，逐根计算模块按自己的入口使用。新增指标、重做注册方式、改行情接口或调整公式需要另行提出方案并评审。

## 8. 实现与验收记录

- 在迁移前提交 `e71214a3b` 的基础上迁移 35 个通用指标 Python 文件。逐文件核对，14 个 SQL 文件和 r4.1 的计算器、版本、状态恢复文件字节一致。识别类型与预判类型拆开，类型定义和图上标记函数的代码保持一致。旧包和被迁移的识别模块在活跃 Python 代码中已无引用。 [共享包打包配置](../../packages/technical_indicators/pyproject.toml) · [配置复制](../../src/foundation/config/settings.py#L153)
- 同一份 `goldenshare_technical_indicators-0.1.0-py3-none-any.whl` 分别安装到 `/private/tmp` 下的两处验证目录。包体 88,697 字节，包含全部 14 个 SQL 文件，SHA-256 为 `5fc911ef9215847e1400d56ad95428c38d38e0af828b8dea568786b3b4730913`。重复离线构建得到相同文件，重建实测 0.703 秒，子进程峰值内存 53.20 MiB。交付源码以本节所在提交为准。
- 在仓库外运行安装产物。价格、MA、BOLL、MACD、KDJ 的三根样本结果与迁移前逐项一致。DG 独立环境未安装 DuckDB、PyArrow 或财势乾坤，仍能运行上证 90 分钟案例，逐根事件、图上标记和保存／恢复的结果与迁移前一致。安装后的两次样本验证实测分别为 0.440 秒和 0.075 秒，含解释器启动，整个前后对照的子进程峰值内存为 148.69 MiB。该结果仅适用于三根指标样本与现有 r4.1 固定案例。
- 迁移前的两批回归用安装后的包复跑，901 项及 851 项通过，用时分别为 9.99 秒及 44.02 秒。额外运行架构边界、现有股票服务和 XXM API、下一根预判等 401 项，全部通过，用时 21.29 秒。Web 测试显式使用临时配置路径，避免仓库 `.env` 把 SQLite 用例切换到本机 DG 来源。旧 D2 缺失诊断夹具的用例仍未选入。现有 `goldenshare ingestion-lint-definitions` 也通过。
- 已验证本地启动脚本的安装开关、发版预检的编译和跳过开关。用 `pip --dry-run` 验证两份 editable 本地安装、CI 带 wheel 的首次安装及预装 wheel 后的发版安装，版本不匹配时按预期失败。`uv lock --check --offline` 通过。根锁文件补入现有配置已声明的 `pypinyin==0.55.0`，其他第三方锁定项一致。GitHub Actions 在推送后运行，正式预装及部署由发布流程执行。
- CodeGraph 用 `explore`、`impact` 核对指标配置、日线装配、历史识别和下一根预判的调用方，迁移后执行 `sync`、`status` 并核对新包已被索引。DG 正式接入范围仍按量化结构数据集自己的方案验收。 [架构快照](codegraph-architecture-snapshot.md)
