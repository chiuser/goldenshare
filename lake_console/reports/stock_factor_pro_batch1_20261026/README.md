# 股票技术因子接入：第一批开发与验收

日期：2026-10-26。范围：原[方案§13](../../docs/design/dagster-stock-technical-factor-onboarding-plan-v1.md)第一批，以及[LLD§14](../../docs/design/dagster-stock-technical-factor-onboarding-low-level-design-v1.md)的契约与基础结构；不提前实施日发布、历史回刷、bootstrap或自动化。

结论：**第一批通过，具备申请第二批的条件**。第二批尚未开始，没有新增业务设计待拍板项；整个数据集和正式运行未验收。

## 实现与计划对账

| 已批准要求 | 代码落点 | 核实方式 |
| --- | --- | --- |
| 源名称直用，独立版本，无旧名别名 | `tushare_download/contract_registry.py`；`contracts/__init__.py` | 仅移除名称必须带版本后缀的限制；保留名称唯一、版本及完整内容校验。空版本/重复名等反例继续拒绝。 |
| 唯一完整261字段与固定请求方式 | `tushare_download/contracts/stk_factor_pro.py`、`dataset_transport_mapping.py` | 名称/数据集/API均为stk_factor_pro，版本1；2字符串及259可空源数值字段。独立解析doc_id=328逐项核名称、顺序、类型和含义；Prod定义只读核对，不运行时导入。 |
| 两种用途、组件扇开及契约分页 | 同一契约及既有planner/HTTP transport | 只登记BY_POINT、BY_OBJECT_RANGE；ISO转YYYYMMDD、按日期升序、limit10000及offset规则。公开load测试验证完整fields与对象扇开，已有分页/重试/通知/取消/关闭回归继续通过。 |
| 本地schema从源契约派生 | `defs/run_contracts/asset_column_schemas.py`、`run_contracts/stk_factor_pro.py` | Raw日期VARCHAR、Silver日期DATE，其余类型和字段顺序一致；没有复制另一份字段清单。 |
| 封闭八字段配置、类型与身份 | `defs/run_contracts/stk_factor_pro.py` | frozen输入及纯解析消费已核日历；未知键、bool冒充整数、错日期/用途/摘要均拒绝。只做输入结构校验，不代替后批业务授权。 |
| 日源内存结果与检查/覆盖基础类型 | 同一run_contracts文件 | 持有原UnitResult及summary，不序列化日下载副本；合法NULL/负指标保留。计数等式、字段变化数、样本数量、检查及覆盖身份有正反例。构造类型不代表业务验证已完成。 |
| 纯路径及专属分区定义 | `defs/paths.py`、`defs/partitions.py` | 正式Raw/Silver、run staging及RecordRef路径不mkdir；拒绝越界、错误run、退役Lake及source/day缓存路径。分区仅定义，不注册正式键。 |
| 不提前装配可运行入口 | 专属Definitions隔离测试及既有治理测试 | 核当前项目定义可加载，并核本数据集资产/check/job/sensor及active catalog尚未登记。不得以空函数或NotImplemented入口占位。 |

本批没有新增env、配置表、共享锁、线程/子进程管理或跨工程import。已存在的其他工作区修改保持原样；`defs/paths.py`只增加本数据集导入和路径函数，不接管其他数据集变更。

CodeGraph用于核对契约登记、下载入口、任务规划、HTTP链路和消费者；其未覆盖的新文件或同名符号以当前代码逐项补核。收尾执行`codegraph sync`和`codegraph status`，仓库根索引状态为up to date；没有重建独立索引。影响面限下载器名称校验/正式登记、本地schema/path/partition及本批测试，无Wealth/API消费者迁移。后批尚未实现的业务授权、PG事实读取及正式装配不在本批冒充验收。

## 测试和真实来源证据

- 定向合并回归：**281 passed，18 warnings，5.62秒**。组成是契约及现有下载器199项、基础结构68项、Dagster框架14项。见[完整输出](targeted-tests.log)及[JUnit结果](targeted-tests.xml)。18项为Dagster分区check的PreviewWarning及其内部时间函数弃用警告，未屏蔽。
- 既有受影响回归：**159项主测试全部通过，另513项子测试通过**；metadata、ETF路径、指数因子34项，资产治理12项，运行合同静态门禁113项。后两组通过既有受保护runner执行；见[汇总](affected-regressions-summary.json)。
- Python静态检查：本批所有修改Python文件默认Ruff通过；全src/tests的E9、F63、F7、F82门禁通过。
- 当前Definitions加载：通过现有受保护runner的固定新增用例，**1 passed，1.45秒**；真实加载并validate_loadable，核无本数据集提前装配。网络、正式路径拒绝及7项原生隔离反例自检通过，实际业务连接0。见[运行日志](definitions-runner.log)和[资源保护证据](definitions-resource-result.json)。1项Pydantic字段属性弃用警告未屏蔽。
- 文档完整性与本批diff空白检查通过；方案/LLD及三个下载器HTML已同步当前登记状态，原框架失败记录仍保留为历史。

合并测试第一次在普通沙箱运行，23项因`HTTPServer.bind(127.0.0.1)`被拒而失败；核实全部为同一权限原因后，在获准环境重跑同一命令得到281项通过，没有修改断言、skip或扩大网络目标。保留初次失败日志在`/private/tmp/stk-factor-batch1-20261026/targeted-tests-sandbox-bind-failure.log`。更早框架首次5项失败及已确认修正继续记载于LLD§14.3.3；当前14项通过不覆盖该历史事实。

真实来源严格复用批准范围：`000001.SZ`，2026-10-12至2026-10-16，全部261字段。共**4次实际请求、0重试**，没有全局读取、扩股票或扩日期：

| 请求 | 参数 | 结果 | 耗时 |
| --- | --- | --- | --- |
| 下载器公开load入口 | BY_OBJECT_RANGE；limit=10000、offset=0 | 5行、261字段；按日期升序交付 | 0.2968秒 |
| 原始HTTP第1页 | limit=2、offset=0 | 2行；7,729字节 | 0.1310秒 |
| 原始HTTP第2页 | limit=2、offset=2 | 2行；7,743字节 | 0.1160秒 |
| 原始HTTP第3页 | limit=2、offset=4 | 1行；5,546字节 | 0.1902秒 |

HTTP固定使用配置基础地址、`http_path_rule="base"`。三页主键没有重叠，其并集和全部261业务值与组件结果一致；报告及可复核的有界行证据见[source/result.json](source/result.json)、[组件结果](source/component-rows.canonical.json)、[第1页](source/page-0-rows.canonical.json)、[第2页](source/page-2-rows.canonical.json)、[第3页](source/page-4-rows.canonical.json)。证据不保存token。

该样本只证明一股五日的字段、区间、小页offset及固定HTTP方式；不证明真实10000行满页边界、全市场覆盖、全市场性能或内存峰值。满页再空、重试同页等由隔离回归验证；真实大边界保留为后续实际接入验收范围，不为制造满页无界拉历史。

本批未操作正式Dagster instance/PG、Lake、Prod、动态分区或runless event；未执行bootstrap、日更、repair、历史回刷或sensor启用。真实Tushare调用是单独批准的有界来源核验，隔离测试只用假token和临时资源。

## 复核命令

工作目录固定为`lake_console/orchestrator`，使用既有环境，不执行安装或依赖同步：

```text
.venv/bin/python3 -B -m pytest -q tests/test_stk_factor_pro_contracts.py tests/test_stk_factor_pro_foundations.py tests/test_stk_factor_pro_dagster_events.py tests/tushare_download
.venv/bin/python3 -B tests/stock_suspend_confirmed_test_runner.py --scope regression --suite test_asset_governance_contracts.py
.venv/bin/python3 -B tests/stock_suspend_confirmed_test_runner.py --scope regression --suite test_run_contract_static_gates.py
.venv/bin/python3 -B tests/stock_suspend_confirmed_test_runner.py --scope regression --suite test_stk_factor_pro_definitions.py
.venv/bin/python3 -B -m pytest -q tests/test_metadata_contracts.py tests/test_etf_daily_paths.py tests/test_idx_factor_pro_contracts.py
.venv/bin/ruff check --no-cache --select E9,F63,F7,F82 src tests
```

来源核验不在收尾时重复请求；后续阶段优先复用本次证据。正式PG、真实写湖、全市场性能和业务链路按原批次分别验收，不能由本报告代替。
