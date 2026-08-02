# Dagster 东方财富行业层级基线低层设计（LLD）

状态：**P0-P3 已完成；东方财富行业层级 Silver 全量快照已正式物化**
创建日期：2026-08-02
适用范围：lake_console/orchestrator 的东方财富行业层级基线；不改现有板块日更链路。

## 1. 目标与事实边界

现有 silver_dc_index[trade_date] 保存东方财富板块的当日目录、名称、等级和 BKxxxx.DC 代码，但没有父级代码或完整层级路径。dc_member 只描述“板块 - 股票”关系，不能可靠推导行业父子关系。

东财已提供一份稳定、最新的三级行业表。它是本专项的分类事实源，不存在可调用接口。本设计把该表固化为可审计、可版本化的 seed，并以一个指定交易日的 silver_dc_index 补齐板块代码，生成可供分析和下游 join 使用的行业层级快照。

### 1.1 已核实事实

| 项目 | 事实 |
| --- | --- |
| 代码参考文件 | silver/board/dc_index/trade_date=2026-07-31/part-000.parquet |
| 行业板块节点数 | 496 |
| 等级分布 | 一级 31、二级 128、三级 337 |
| 参考文件大小 | 50 KiB |
| 仅投影 level/name/ts_code 的 DuckDB 读取 | 496 行，命令运行约 0.02 秒 |
| 东财来源材料 | 用户提供的三级行业表图片；SHA-256 为 7b499617be0ddfa129bade02dc54922d4bb158a931423b6b85855382d7946299 |

### 1.2 P0 基线冻结结果

P0 直接读取用户提供的原图网格，不使用外部分类资料。原图的三级列共有 339 个节点格；其中 `储能` 与 `其他多元金融` 已由运营明确裁定为当前已取消、不纳入 DG，因此正式 seed 为 496 行。

| 项目 | P0 核验结果 |
| --- | --- |
| 原图网格节点格 | 一级 31、二级 128、三级 339 |
| 正式 seed 节点 | 一级 31、二级 128、三级 337，共 496 |
| 正式 seed SHA-256 | 36f603dc6a9e50e1194a24fb53b6e47c0cdf99ef0df241c4d5cf38446480210c |
| 代码参考目录 | `silver_dc_index[2026-07-31]`；文件 SHA-256 为 `9d54e4e9d1a4816f42753aee6a200c6e9fe255cf49eec438c2460fbf0e1b7c13` |
| 严格双向映射 | 按“等级 + 名称”比较，seed 减 reference = 0，reference 减 seed = 0；无重复 `(level, name)`、无重复 BK 代码、无空关键字段 |

已完成 496 行名称与等级的零差异证明；P2 仍必须对运营当次指定的参考日重新做同一双向 preflight，不能复用 P0 的文件 hash 代替未来运行事实。

## 2. 已确认决策

1. 唯一正式 asset 为 silver_dc_industry_hierarchy，数据集 ID 为 dc_industry_hierarchy。
2. 它是无分区、单文件的 Silver 全量快照，不是按交易日生成的行情数据。
3. 不创建 Raw asset：没有接口、请求原文或分页过程；版本化 seed 是原始分类事实的留存载体。
4. 不创建 sensor、schedule、dynamic partition、readiness helper、cursor 或历史 runless event。它不参与日常自动触发。
5. 只创建一个手动 job：silver_dc_industry_hierarchy_update_job。它只选择该 asset 和唯一核心 blocking check。
6. silver_dc_index 仅是代码补全参考，不替代东财层级事实；不从 dc_member、成分股重叠或板块日线反推父子关系。
7. 名称匹配采用“等级 + 去首尾空白后的名称”严格一对一匹配；不做模糊匹配、别名表、静默修正或 fallback。
8. SourceSystem 使用既有 SEED，不新增“seed + derived”混合来源枚举。代码补全依据写入 metadata。
9. 官方生效日期未知，不伪造该字段。首版记录 baseline_version 与 source_received_date=2026-08-02；后者是运营收到该表的日期，不是东财发布或生效日期。
10. 东财图片与结构化 CSV 一并纳入版本控制。未来分类变更新增版本化 seed，不覆盖旧 seed 文件；当前 Lake 快照只保留手动 job 选择的版本。

## 3. Dagster 资产契约

| 类型 | 名称 | 说明 |
| --- | --- | --- |
| asset | silver_dc_industry_hierarchy | 当前有效东财行业层级及 BK 代码的 Silver 全量快照 |
| check | silver_dc_industry_hierarchy_core_check | 唯一聚合 blocking check；以 rule summary 表达文件、树和映射事实 |
| job | silver_dc_industry_hierarchy_update_job | 手动重建单一全量快照，并执行唯一 check |
| sensor / schedule | 无 | 东财表稳定且没有接口；日常运行只会制造无意义事件 |

asset 采用下列稳定定义：

~~~
group_name: board
layer: silver
data_domain: basic_data
source_system: seed
data_contract: eastmoney_dc_industry_hierarchy_with_board_codes_full_snapshot
~~~

不在 @dg.asset(...) 声明无限定的 deps=[silver_dc_index]。原因是上游是交易日分区资产，而该 asset 必须只读取一个由本次 run config 明确给出的参考日；无分区 downstream 对动态分区 upstream 的默认映射会模糊为“依赖哪些日期”。

取而代之，definition metadata 固定记录 code_reference_asset=silver_dc_index；本次 materialization metadata 固定记录实际的 code_reference_trade_date、路径、代码数和 hash。这样保留可审计关系，也不会把所有历史 silver_dc_index 分区误建成输入依赖。

## 4. 路径与输出 schema

### 4.1 物理路径与写入方式

~~~
/Volumes/datasource/data_lake/
  silver/board/dc_industry_hierarchy/full/part-000.parquet
~~~

新增 helper：

~~~
def silver_dc_industry_hierarchy_path(root: Path) -> Path:
    return lake_path(
        root,
        SILVER,
        "board",
        "dc_industry_hierarchy",
        "full",
        "part-000.parquet",
    )
~~~

使用既有 WritePolicy.SINGLE_FILE_ATOMIC_REPLACE：同目录 staging 写入、回读验证、os.replace(...) 提升。失败时删除临时文件，既有正式快照不变。不得新增锁文件；运营一次只手动运行一个该 job。

### 4.2 输出字段

新增 SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA，列顺序固定：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| ts_code | VARCHAR | 当前 silver_dc_index 对应的 BKxxxx.DC 行业板块代码 |
| name | VARCHAR | 东财行业名称 |
| industry_level | INTEGER | 行业等级：1、2 或 3 |
| industry_level_name | VARCHAR | 东财一级、二级或三级行业 |
| parent_ts_code | VARCHAR | 父级行业代码；一级行业为空 |
| parent_name | VARCHAR | 父级行业名称；一级行业为空 |
| root_ts_code | VARCHAR | 所属一级行业代码 |
| root_name | VARCHAR | 所属一级行业名称 |
| hierarchy_path | VARCHAR | 人类可读路径，例如 电子 > 半导体 > 集成电路制造 |
| is_leaf | BOOLEAN | 当前节点是否没有子行业 |
| display_order | INTEGER | 东财表中的前序展示顺序 |
| baseline_version | VARCHAR | 结构化 seed 版本 |
| source_received_date | DATE | 运营收到该版东财表的日期，不是官方生效日期 |
| code_reference_trade_date | DATE | 本次补齐 BK 代码所用 silver_dc_index 交易日 |

hierarchy_path 是普通 VARCHAR，不用 JSON：树关系已经由父级和根级代码表达，路径只服务于人读和简单分组，避免无意义的 JSON 类型与解析成本。

## 5. Seed 与来源留存

### 5.1 新增文件

| 文件 | 职责 |
| --- | --- |
| src/orchestrator/seeds/board/eastmoney_dc_industry_hierarchy.cn_a.v1.source.png | 东财原始表的版本化证据；运行时不读取 |
| src/orchestrator/seeds/board/eastmoney_dc_industry_hierarchy.cn_a.v1.csv | P0 由原图网格结构恢复并严格核验的可执行 seed |
| src/orchestrator/seeds/board/eastmoney_dc_industry_hierarchy.py | seed 常量、数据类、CSV loader、hash 与树校验 |
| src/orchestrator/seeds/board/__init__.py | 新 seed package |

原图复制后必须核对 SHA-256 与第 1.1 节一致。CSV 使用 UTF-8，保留中文；不允许把当前碎裂的 OCR 输出直接作为 seed。P0 使用原图列网格恢复父子关系，并以当前 DG 目录做严格名称核验；`储能`、`其他多元金融` 的排除是运营明确裁定，不是 OCR 推断。

### 5.2 CSV 契约

~~~
node_path,parent_path,industry_level,name,display_order
电子,,1,电子,1
电子/半导体,电子,2,半导体,2
电子/半导体/集成电路制造,电子/半导体,3,集成电路制造,3
~~~

node_path 是 seed 内稳定树标识；parent_path 是直接父节点标识。名称中禁止 /，防止路径歧义。CSV 不保存 BK 代码，避免把可能变化的目录代码人工硬编码进分类事实。

### 5.3 loader 校验

load_eastmoney_dc_industry_hierarchy_seed(...) 必须拒绝：

1. 缺失文件、空文件、header 或列顺序不精确。
2. 空路径、空名称、非法等级、非法展示顺序或名称含 /。
3. 重复 node_path、重复 display_order、路径层级与 industry_level 不一致。
4. 一级节点带父级，二三级节点缺父级，父级不存在，或父级等级不是当前等级减一。
5. 环、孤儿节点，或同一路径下名称与最后一段不一致。
6. 层级数量不是一级 31、二级 128、三级 337，或总数不是 496。

loader 返回不可变 EastmoneyDcIndustryHierarchySeedRow 集合，并提供版本、来源接收日和 seed 文件 SHA-256。它不得访问 Lake、Dagster instance、Tushare、prod 或网络。

## 6. BK 代码映射与写入

### 6.1 唯一 run config

在 defs/run_contracts/configs.py 新增：

~~~
class DcIndustryHierarchyConfig(dg.Config):
    reference_trade_date: str

def build_silver_dc_industry_hierarchy_update_job_run_config(
    reference_trade_date: str,
) -> dict[str, object]: ...
~~~

reference_trade_date 必须为 ISO YYYY-MM-DD，且是本次唯一允许读取的 silver_dc_index 分区。它不是默认值、环境变量、cursor 或隐藏的“取最新”逻辑。

### 6.2 参考目录读取

asset 只读取：

~~~
silver/board/dc_index/trade_date=<reference_trade_date>/part-000.parquet
~~~

DuckDB SQL 必须显式投影：

~~~
SELECT
  upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
  trim(CAST(name AS VARCHAR)) AS name,
  trim(CAST(level AS VARCHAR)) AS level
FROM read_parquet(..., hive_partitioning = false)
WHERE idx_type = '行业板块'
~~~

不读行情字段、成分股或其它日期文件。先验证：

1. ts_code 匹配 ^BK[0-9]{4}\.DC$，名称和等级非空。
2. 正式 `level` 保持 `东财一级行业`、`东财二级行业`、`东财三级行业` 三个中文枚举；只在 SQL 中显式映射为 1、2、3，禁止假设为 `L1/L2/L3` 或从字符串末尾推断。
3. 每个 (level, name) 对应唯一 BK 代码；每个 BK 代码对应唯一 (level, name)。
4. 等级只允许三个东财行业等级，且数量精确为 31/128/337。

### 6.3 严格双向映射

~~~
1 -> 东财一级行业
2 -> 东财二级行业
3 -> 东财三级行业
~~~

以 (industry_level_name, name) 进行完全等值 join。写入前必须同时满足：

~~~
seed 节点 - reference 节点 = 0
reference 节点 - seed 节点 = 0
~~~

任一缺失、额外、重复或等级不一致都 fail closed。异常文本和 metadata 每类最多保留 20 个样本，不写完整节点集合。

映射成功后，通过 parent_path 自连接生成父级代码和名称，并生成根代码、根名称与 hierarchy_path。is_leaf 由是否存在子节点计算，不从“三级必是叶子”的假设得出。

### 6.4 writer 函数

新增 defs/assets/dc_industry_hierarchy.py：

| 符号 | 职责 |
| --- | --- |
| load_dc_industry_hierarchy_reference(...) | 读取并验证单个 silver_dc_index 参考文件 |
| audit_dc_industry_hierarchy_reference(...) | 返回 seed/reference 双向差集、重复和有限样本 |
| build_dc_industry_hierarchy_select_sql(...) | 生成全量 set-based 输出 SQL |
| write_silver_dc_industry_hierarchy_snapshot(...) | staging 写入、回读验证、原子提升 |
| silver_dc_industry_hierarchy(...) | Dagster asset 入口、stdout 里程碑和 materialization metadata |

Python 只做 seed loader、路径和结果对象组织；496 行树与目录 join、父级关联、叶节点计算和 Parquet 写入全部用 DuckDB set-based SQL。不得逐行写 Parquet 或把完整行集合写入 metadata。

staging 回读必须验证：输出 schema、496 行、ts_code 和 hierarchy_path 唯一、层级数量、父级/根级闭合、引用日一致、代码正则、空键数为零。全部通过后才 os.replace(...)。

## 7. Metadata、日志与核心 check

### 7.1 asset metadata 与日志

definition metadata 必须包含：

~~~
dataset_id=dc_industry_hierarchy
source_system=seed
data_contract=eastmoney_dc_industry_hierarchy_with_board_codes_full_snapshot
dagster/column_schema=SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA
path_template=silver/board/dc_industry_hierarchy/full/part-000.parquet
seed_version=eastmoney_dc_industry_hierarchy.cn_a.v1
code_reference_asset=silver_dc_index
~~~

runtime materialization metadata 只记录本次事实：

~~~
summary / next_action / result_status / diagnostic_ref
seed_file_path / seed_sha256 / seed_node_count
code_reference_trade_date / code_reference_file_path
code_reference_node_count / code_reference_hash
output_row_count / level_count_distribution
observed_columns / elapsed_ms
~~~

使用 DgStdoutLogger("dc_industry_hierarchy")，只输出：

~~~
dc_industry_hierarchy_started
dc_industry_hierarchy_reference_validated
dc_industry_hierarchy_completed
dc_industry_hierarchy_validation_failed
~~~

日志不打印完整节点、SQL、seed 全文或来源图片内容。

### 7.2 唯一核心 check

新增 defs/checks/dc_industry_hierarchy_checks.py，其中唯一的 silver_dc_industry_hierarchy_core_check 是 blocking=True、无分区的聚合 check。它验证已写出快照及本次 metadata 声明的参考日，不二次计算分类事实。

规则：

1. 文件存在、非空，schema 与 definition contract 一致。
2. 496 行和 31/128/337 层级分布。
3. ts_code、hierarchy_path 唯一且非空，代码格式合法。
4. 每个非根节点存在同等级减一的父节点；根节点、路径、根代码闭合；没有环或孤儿。
5. baseline_version、source_received_date 与当前 loader contract 一致。
6. 输出 (industry_level_name, name, ts_code) 与唯一参考日 silver_dc_index 双向覆盖一致。

一个 check event 内用 failed_rule_names、rule_summary、中文 summary、next_action 和有限样本说明问题。这是本项目已经确认的“每资产一个核心 check”治理口径，避免为稳定小型基线制造细碎 Dagster DB 状态。

## 8. Catalog 与 Definitions 装配

| 文件 | 精确变更 |
| --- | --- |
| defs/paths.py | 新增 silver_dc_industry_hierarchy_path(root) |
| defs/run_contracts/asset_column_schemas.py | 新增 SILVER_DC_INDUSTRY_HIERARCHY_SCHEMA |
| defs/run_contracts/configs.py | 新增 `DcIndustryHierarchyConfig` 与 run-config builder |
| defs/catalog/name_mapping.py | 新增 dc_industry_hierarchy: 东方财富行业层级 |
| defs/catalog/lake_assets.py | 新增 full-file partition model、check tuple、path/schema imports 和一个 SourceSystem.SEED 的直接 _entry(...) |
| defs/assets/dc_industry_hierarchy.py | 新 asset 与 set-based snapshot writer |
| defs/checks/dc_industry_hierarchy_checks.py | 唯一核心 blocking check |
| defs/jobs/dc_industry_hierarchy.py | 手动更新 job；selection 只含 asset 与其 check |

Catalog entry 不得使用 _derived_entry(...)，该 helper 会把来源错误标为 DERIVED。必须直接使用既有 _entry(...)：

~~~
source_system=SourceSystem.SEED
data_contract_source=DataContractSource.SEED_CONTRACT
ingestion_sources=(IngestionSource.SEED_FILE,)
default_daily_ingestion_source=None
bootstrap_sources=()
partition_model=FULL_FILE_SILVER_DC_INDUSTRY_HIERARCHY
write_policy=SINGLE_FILE_ATOMIC_REPLACE
event_policy=DAGSTER_RUN_ONLY
compute_engine=DUCKDB_SQL
~~~

definitions.py 已通过 load_from_defs_folder(...) 自动装配新文件，不改 definitions composition root。

## 9. 明确不改的边界

不修改下列现有链路、数据或状态：

~~~
assets/dc_board_raw.py
assets/dc_board_silver.py
checks/dc_board_checks.py
checks/dc_board_silver_checks.py
sensors/dc_board_sensor.py
sensors/dc_board_silver_sensor.py
sensors/dc_board_partition_sensor.py
jobs/dc_board.py
jobs/dc_board_silver.py
所有 dc_* dynamic partitions、现有 Parquet、Dagster event/check/run 历史
~~~

因此本专项不会改变 DC 板块日线更新时机、M10 prod/Tushare 完整性门禁、sensor cursor、分区注册或下游技术指标。

## 10. 性能模型与停止策略

| 入口 | 最大读取 | 最大写入 | 预算与失败策略 |
| --- | --- | --- | --- |
| 手动 asset run | 1 个 seed CSV（496 行）+ 1 个指定日期 silver_dc_index 文件（约 50 KiB，仅 3 列） | 1 个约 496 行 Parquet + 1 条 materialization | 无网络、无远程 DB、无历史日期扫描；映射异常 fail closed |
| core check | 1 个输出文件 + 1 个 metadata 指定参考文件 | 1 条 check event | 只读两份小文件；不请求 Tushare、不读 dc_member |
| 日常 sensor | 0 | 0 | 本专项没有 sensor，零稳态成本 |

首次正式写入前必须执行只读 preflight，输出 /private/tmp/dc_industry_hierarchy_preflight_<timestamp>.json，至少冻结：seed SHA-256、图像 SHA-256、参考日期、参考文件 SHA-256、三层计数、双向差集、重复项、节点数和预计输出行数。任一不符即停止，不写 Lake 或 Dagster instance。

## 11. 测试与静态门禁

### 11.1 新增测试

| 测试文件 | 必测事实 |
| --- | --- |
| tests/test_dc_industry_hierarchy_seed.py | 原图 hash、精确 header、496 节点与 31/128/337、路径/父级/展示顺序/重复/环/孤儿拒绝 |
| tests/test_dc_industry_hierarchy_asset.py | 完整映射、缺/多/重复参考节点、非法 BK 代码、等级错配、原子替换、失败不覆盖既有目标、metadata 仅摘要 |
| tests/test_dc_industry_hierarchy_checks.py | 唯一 core check 的正常、缺文件、schema 错、key 重复、父级断裂、映射差异、有限样本和 blocking 语义 |
| tests/test_run_contract_configs.py | ISO 日期、空日期、伪造日期 config 的接受/拒绝与 job target |

### 11.2 更新测试

| 文件 | 更新内容 |
| --- | --- |
| tests/test_asset_governance_contracts.py | catalog、asset tags、definition schema、路径、唯一 blocking check 和 full-file model 一致 |
| tests/test_run_contract_static_gates.py | 禁止该 asset 使用 Tushare、prod DB、dc_member、动态分区、sensor、模糊匹配、SELECT *、逐行 Parquet 写入或无界 metadata |

### 11.3 编码阶段验证

~~~
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run python -m unittest \
  tests.test_dc_industry_hierarchy_seed \
  tests.test_dc_industry_hierarchy_asset \
  tests.test_dc_industry_hierarchy_checks \
  tests.test_run_contract_configs \
  tests.test_asset_governance_contracts \
  tests.test_run_contract_static_gates
git diff --check
~~~

dg check defs、正式 instance preflight、正式 Lake materialization 和 job 运行不属于编码阶段，分别单独审批。

## 12. 推进顺序与验收

### P0：结构化来源核验（已完成）

1. 已复制并 hash 校验东财原图。
2. 已按原图列网格恢复层级路径；网格、节点与两项运营裁定排除均写入 P0 审计结果。
3. 已生成 496 行候选 seed，并完成完整树、层级计数和连续展示顺序校验；对应 loader 与本地 seed tests 已纳入 P0 实现。
4. 已对 `silver_dc_index[2026-07-31]` 做严格双向差集，差集、重复和空关键字段均为零。P1 可以开始，但首次正式 materialization 前仍需运行 P2 的新鲜只读 preflight。

### P1：代码与本地测试（已完成）

1. 已实现 `silver_dc_industry_hierarchy` 无分区 asset、唯一核心 blocking check、手动 job、typed run config、路径/schema 与 `SourceSystem.SEED` catalog entry；未创建 sensor、schedule、动态分区、readiness helper 或 runless event。
2. writer 只读取版本化 seed CSV 与 config 指定的一份 `silver_dc_index` 行业目录。它先做 reference 结构校验和 seed/reference 双向映射，再用 DuckDB set-based SQL 写 staging、回读验证并以 `os.replace(...)` 原子提升。
3. 本地临时 Lake fixture 已验证正常完整映射、缺目录节点、重复 `(level, name)`、非法 BK 代码、staging promote 失败不覆盖旧文件、缺文件/缺 metadata、错误 schema 及唯一 core check 的 blocking 语义。
4. 已执行：

   ~~~
   uv run python -m unittest \
     tests.test_dc_industry_hierarchy_seed \
     tests.test_dc_industry_hierarchy_asset \
     tests.test_dc_industry_hierarchy_checks \
     tests.test_run_contract_configs \
     tests.test_asset_check_incremental_governance \
     tests.test_run_contract_static_gates
   git diff --check
   ~~~

   结果：125 个测试通过；没有运行 `dg check defs`，没有访问正式 Lake、Dagster instance、prod、Tushare 或网络。

5. `tests.test_asset_governance_contracts` 已加入本 asset 的 active 定义，但其全仓聚合断言当前仍遗漏 14 个既有 `index_mins/index_global` active asset，导致 catalog 总数与该测试内手工清单相差固定 14。该已存在的全仓测试基线问题不在本专项修改范围内；本专项通过了自己的 asset/catalog 一致性测试和增量治理测试，不以该失败用例作为 P1 通过证据。
6. P2 首次 preflight 发现本机 fixture 错把正式 `silver_dc_index.level` 模拟为 `L1/L2/L3`。已将 asset、core check 与 fixture 统一改为正式中文枚举 `东财一级行业/东财二级行业/东财三级行业`，并只通过显式 SQL `CASE` 映射为整数等级；禁止从字符串末尾推断等级。

### P2：正式只读 preflight（已完成）

1. 已使用 P0 冻结的 `silver_dc_index[2026-07-31]`，未采用隐式“最新可见日期”。
2. 已生成 [P2 preflight 报告](/private/tmp/dc_industry_hierarchy_preflight_20260802_185418.json)：seed SHA-256 为 `36f603dc6a9e50e1194a24fb53b6e47c0cdf99ef0df241c4d5cf38446480210c`，参考 Parquet SHA-256 为 `9d54e4e9d1a4816f42753aee6a200c6e9fe255cf49eec438c2460fbf0e1b7c13`，496 节点、31/128/337 层级分布、双向差集、重复与空关键字段均通过。
3. 正式目标路径在 P3 前不存在；本阶段只写入 `/private/tmp` 审计报告，未写 Lake、Dagster instance、prod 或网络。
4. P3 仍须单独批准一次正式 Lake materialization 和对应手动 job 运行。

### P3：首次正式 materialization（已完成）

1. 已在 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home` 运行 `silver_dc_industry_hierarchy_update_job`，唯一 config 为 `reference_trade_date=2026-07-31`。本次 run 为 `46122f97-9f3a-4582-9568-b0649857b578`，materialization storage id 为 `6844063`。
2. [P3 post-audit 报告](/private/tmp/dc_industry_hierarchy_p3_post_audit_20260802.json) 已确认：输出为 496 行，schema、31/128/337 层级分布、键唯一性、父级/根级闭合、baseline、seed/reference 双向映射均为零失败；唯一 blocking core check 为 `SUCCEEDED`，且绑定 storage id `6844063`。
3. 未补历史 event、未添加日期分区、未修改或重跑任何现有 DC 链路；本资产保持手动全量快照，不引入 sensor 或 schedule。

## 13. 停止条件

出现任一情况必须停止，不以别名、手工 BK 代码或文件覆盖绕过：

1. 转录 seed 不是精确的 31/128/337/496 树，或原图 hash 不符。
2. seed 与指定 silver_dc_index 出现任意名称/等级双向差集、重复或非法代码。
3. 需要从 dc_member、成分股重叠或板块行情推断层级才能形成输出。
4. 需要按每日/历史日期扫描、建立 sensor、动态分区或新增状态资产才能运行。
5. staging 验证失败，或任何失败路径可能覆盖既有正式快照。
6. 代码实现发现必须改变现有 DC Raw/Silver/sensor/job 行为才能接入。

## 14. 依据与影响面审计

本 LLD 已核对：

1. silver_dc_index 的 schema、路径、专属交易日分区、M10 Raw/Silver 链路和其唯一核心 check 结构。
2. stock_identity_map 与 market_major_indices 的版本化 seed、full snapshot、job 与 metadata 模式。
3. LAKE_ASSET_CATALOG 的 full-file partition model、单文件原子替换、SourceSystem.SEED、IngestionSource.SEED_FILE 和 DataContractSource.SEED_CONTRACT。
4. definitions.py 的 load_from_defs_folder(...) 自动装配行为。
5. CodeGraph：load_stock_identity_mapping_seed 的消费者局限于其现有资产、检查和测试；本专项新增独立 seeds/board 模块，不修改这些消费者。LAKE_ASSET_CATALOG 的影响面由 catalog 与治理测试承接。
6. Dagster 官方 asset/check 文档：稳定 schema 进入 definition metadata；check 可随 asset job 执行。项目的单核心 check 是为控制本地 Dagster DB 状态量而确认的治理口径。
