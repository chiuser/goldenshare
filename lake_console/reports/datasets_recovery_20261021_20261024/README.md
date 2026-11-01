# 2026-10-21 DG 数据集补齐说明

## 报告附件清理（2026-11-01）

管理员已明确要求删除无用过程材料。本目录由24个文件精简为2个，删除22个；只保留本文及下列最终审计/必要结果。过程附件、重复状态/配置、旧脚本、测试输出和逐文件清单已删除，不另打包保存。本文原章节及当时操作结论保留；已删除附件的链接转到本节，不能再据旧裸路径要求恢复文件或重新补数。此次没有读取行情或数据库、触发任务、更改sensor或删除正式Lake/staging记录。

- [final-verified.json](final-verified.json)

全部五个目录的范围与执行规则见[原LLD20.16](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#2016-五个恢复报告目录的精简2026-11-01)。

执行日期：2026-10-24，全部时间使用北京时间。管理员已批准先补齐主要指数 38 项，全部正常后继续补齐资金流 2 项。按管理员最新要求，方案、操作和结果集中记录在本说明，不修改原方案或 LLD。执行结果：40 项全部补齐，7 个 job 和 97 项检查全部通过。执行前检查与逐步操作保留在下文，最后验收见第 10 节。

## 1. 已确认的缺失

最新物理审计检查 159 项日期相关数据集：119 项有数据，40 项缺少目标文件；另外 21 项不适用此次日期完整性判断。没有发现零行文件、不可读文件或服务表日期记录缺失。

与原先 50 项缺失比较，恰好补上 ETF 分钟线 Raw、Silver 各 5 项，共 10 项，没有新增缺失。

| 范围 | 缺失数 |
| --- | ---: |
| 主要指数分钟线 Raw：5、15、30、60 分钟 | 4 |
| 主要指数分钟线 Silver | 7 |
| 主要指数分钟线 Gold | 7 |
| 主要指数分钟九转 | 6 |
| 主要指数分钟技术指标 | 7 |
| 主要指数分钟技术指标状态 | 7 |
| THS 个股资金流 Raw、Silver | 2 |
| 合计 | 40 |

主要指数共 38 项，其中 4 项 Raw 缺失使后续 34 项未能生成。主要指数 1 分钟 Raw 文件已经存在，共 2,410 行。

## 2. 为什么没有自动补上

### 主要指数

10 月 21 日 Raw 任务 `a5df6a20-4747-4630-94bc-28f9029fdee4` 在当日 17:14:40（北京时间）启动，4 个频率没有取得全部应有指数的数据。1 分钟成功，其余 4 个频率失败。

当前自动重试只处理一个频率缺失的情况。此次缺失 4 个频率，sensor 明确记录 `raw_retry_scope_not_single_frequency`，因此需要人工启动恢复；Silver 等后续任务一直等待上游齐备。当前 daemon 没有运行，也不能依赖等待自动推进。

### THS 个股资金流

Raw 任务 `98aac9d5-53e8-4b5b-81e4-1b81e0ff07a7` 因 300830.SZ 当天的 `net_d5_amount`、`buy_lg_amount_rate`、`buy_md_amount_rate` 出现 NaN 而拒绝发布。该错误被标为不可自动重试，Silver 因没有合格 Raw 而未生成。

不应通过填零、删除记录或放宽检查绕过这次错误。

## 3. 现在具备的条件与证据边界

- 已核验主要指数 10 个代码 × 4 个缺失频率的 15:00 收盘样本，40/40 均返回一行，代码、频率、时间及完整请求字段符合要求。这支持重新获取当天数据，但不证明全日分钟时间点已经齐全。
- 300830.SZ 的上述三个字段现在分别返回 -408.13、-8.27、-5.23，均为正常有限数值。这只证明之前的错误记录恢复，不能代替当天全市场校验。
- 10 月 20 日所需前序文件均存在；本次核对的技术指标及状态、九转检查均通过，且对应当前前序物化记录。正式计算仍须按原实现读取并校验所需历史输入。
- 相关 7 个 job 没有正在运行的任务。两个日期分区均已注册，不需要新增分区。
- 两条 Raw 链均直接读取 Tushare，不需要从 Prod 重新导入。

当前代码支持复用现有入口完成恢复，没有证据要求先修改代码或自动重试策略。

## 4. 已批准的执行顺序

全部只处理分区 `2026-10-21`。每个任务成功、对应物理文件与检查通过后，再推进下一步。

| 顺序 | 现有 job | 预期新增文件 |
| --- | --- | ---: |
| 1 | `raw_major_index_mins_update_job` | 4 |
| 2 | `silver_major_index_mins_update_job` | 7 |
| 3 | `gold_major_index_mins_update_job` | 7 |
| 4 | `gold_major_index_mins_nineturn_update_job` | 6 |
| 5 | `gold_major_index_mins_technical_daily_update_job` | 14 |
| 6 | `raw_tushare_moneyflow_ths_update_job` | 1 |
| 7 | `silver_moneyflow_ths_update_job` | 1 |
| 合计 | | 40 |

第 1 步使用完整的现有五频率 job。writer 会完整校验已有 1 分钟文件，合格后复用且不请求源端；不合格则停止，不覆盖已有文件。4 个缺失频率按当天 10 个代码取数，预计新增 800 行，正常情况下共 40 次源请求。

第 5 步同时生成技术指标和状态，各 7 个文件，不能只选择其中一半。九转按现有实现读取最多 20 个日期的 Gold 输入及前序九转结果；技术指标按现有实现读取当天 Gold 与前序状态，不重算或覆盖 10 月 20 日。

资金流 Raw 使用现有两轮读取和稳定性校验，每页 2,000 行，两轮至少间隔 60 秒，全部业务字段一致且数值检查通过后才发布。Silver 继续要求 Raw 检查与当前文件对应，不跳过检查。

预期是新增 40 个文件；由于第 1 步还会校验复用已有 1 分钟文件，选择的物化输出共 41 项。这两个数量不能混用。

## 5. 失败、续跑与开销

- 不重启 daemon，不修改 sensor，不扩展到 10 月 22 日或其他日期，不覆盖已存在且合格的文件。
- 任一步失败即停止其后续链路，保留已经成功发布的数据。先读取失败原因、checkpoint 和目标文件，再按现有幂等规则确定续跑范围，不重新执行全部 7 个任务。
- 主要指数缺失频率正常取数共 40 次请求；当前请求策略的 300 秒限额针对每个频率 writer，不能当作整个 job 的总耗时保证。重试和超时受原策略约束，不临时放大预算。
- 资金流每轮最多 20,000 行，两轮共享 300 秒预算、最多 64 次请求。没有重试时，请求数为 `2 × (floor(N / 2000) + 1)`，包含整页末尾的空页；不能把它估算成只有两次请求。两轮间隔意味着正常运行本身至少需要 60 秒。
- 中断后优先复用已经发布的合格文件；尚未发布的资金流候选仍须完成原有两轮一致性检查，不拿中断前单轮结果直接发布。
- 每一步复用任务本身的完整检查，额外只核对该步文件、行数及对应的检查记录。最终只对本次 40 项及其必要依赖做一次汇总验收，不反复重跑 159 项审计或全日源端比对。
- 本次收盘样本和资金流错误样本已核验，正式执行前不再重复获取同一批抽样证据。

## 6. 本次执行约束与代码复核

本次没有修改代码。原方案与 LLD 继续约束既有资产合同；管理员明确要求本次恢复说明独立记录，因此不向原文档追加日常操作记录。

工作目录固定 `/Users/congming/github/goldenshare/lake_console/orchestrator`，正式 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`。复用现有 `.venv/bin/dg` 与登录 shell 环境，不安装依赖，不输出密钥，不使用 uv 自动同步。每一步完整命令如下（标准输出和错误分别保存到本报告目录的对应日志中）：

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job raw_major_index_mins_update_job --partition 2026-10-21
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job silver_major_index_mins_update_job --partition 2026-10-21
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job gold_major_index_mins_update_job --partition 2026-10-21
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job gold_major_index_mins_nineturn_update_job --partition 2026-10-21
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job gold_major_index_mins_technical_daily_update_job --partition 2026-10-21
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job raw_tushare_moneyflow_ths_update_job --partition 2026-10-21
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --job silver_moneyflow_ths_update_job --partition 2026-10-21
```

读范围是当天源数据、当天已有上游文件及当前算法需要的前序输入；写范围只限当天目标文件、对应 staging 和原生 run/materialization/check 事件，不写 Prod，不执行 runless 事件或其它分区任务。预检只查本次 41 个目标文件、相关 7 个 job 的活动状态、分区已注册、daemon 未运行和磁盘条件；另保存 20/22 日同一范围文件 stat 供最终确认没有改动。20 日前序检查及 40 个源样本复用此前审计证据。

| 项目 | 本次预算与拒绝条件 |
| --- | --- |
| 日期、代码、输出 | 1 日、主要指数 10 个代码；40 个新增文件及 1 个复用文件 |
| 主要指数取数 | 正常 40 次请求、800 行新增 Raw；每频率沿用 300 秒请求预算，不放大 |
| 资金流取数 | 单轮最多 20,000 行、2 轮、每页 2,000；总计最多 64 次请求、300 秒，间隔至少 60 秒 |
| 本地读取 | 主要指数 Silver/Gold 仅当日小文件；九转六频各最多 20 日上下文，另读前日九转；技术指标读取当天 Gold 与前日状态；资金流按原行数检查读取前五个日期参考证明；不扫描全部历史明细 |
| 内存与空间 | 沿用现有资源限制：主要指数 DuckDB 每连接 16GB、4 线程上限；资金流沿用 512MB/单线程候选连接及 RSS 门禁；预检必须满足现有资金流 64GiB 空闲要求，新增文件和候选预计远小于 1GiB |
| 耗时 | 正常预计数分钟，资金流至少 60 秒；总计 15 分钟作为人工复核告警，不因告警扩大范围或放宽原生超时 |
| 失败和中断 | 只保留已成功输出；先读失败原因和实际文件，不自动重跑整链。主要指数 Raw 可复用合格输出；其它步骤恢复前按其当前 writer/checkpoint 语义核验，不能假定所有 job 都可无条件重放 |
| 每步验收 | 读取本次 run 的物化与检查事件（每次最多 500 条），要求 SUCCESS、输出集合正确、全部要求检查通过且绑定当前同日物化，目标文件存在 |
| 最后验收 | 对 41 个目标文件统一读回一次行数、schema、文件 hash，结合本次已通过检查，不重复公式计算或全文件差集；比较前后缺失集合与 20/22 日相关文件 stat，额外读取预计秒级 |
| 续跑开销 | 已发布合格数据不重复源端读取；未完成资金流取数仍需两轮证明。任何重试均记实际操作，不预设无限重跑预算 |

没有改变配置默认值、字段合同、检查、自动重试、任务选择或运行入口；不需要新增单元测试。当前代码复核和源样本支持进入已批准正式补齐，最终通过以实际原生任务和文件读回为准。

## 7. 当前代码依据

- `lake_console/orchestrator/src/orchestrator/defs/assets/major_index_mins_raw.py`
- `lake_console/orchestrator/src/orchestrator/defs/io/major_index_mins_raw_writer.py`：已有目标文件完整校验与复用。
- `lake_console/orchestrator/src/orchestrator/defs/sensors/major_index_mins_sensor.py`：只允许单一缺失频率自动重试。
- `lake_console/orchestrator/src/orchestrator/defs/assets/major_index_mins_silver.py`
- `lake_console/orchestrator/src/orchestrator/defs/assets/major_index_mins_gold.py`
- `lake_console/orchestrator/src/orchestrator/defs/assets/major_index_mins_technical.py`
- `lake_console/orchestrator/src/orchestrator/defs/assets/moneyflow_ths.py`
- `lake_console/orchestrator/src/orchestrator/defs/io/moneyflow_daily_update.py`
- `lake_console/orchestrator/src/orchestrator/defs/source_readiness/moneyflow_daily.py`

已使用 CodeGraph 定位并检查主要指数 Raw writer 的入口、调用方和复用/拒绝覆盖测试，再逐项阅读实际资产、writer、sensor 与资金流实现。本轮不涉及代码变更，没有以单元测试结果替代真实审计。

## 8. 执行前审计证据

- [执行前物理审计（附件已清理）](README.md#报告附件清理2026-11-01)
- [与原 50 项缺失比较（附件已清理）](README.md#报告附件清理2026-11-01)
- [DG 运行、sensor、前序检查证据（附件已清理）](README.md#报告附件清理2026-11-01)
- [Tushare 有界样本（附件已清理）](README.md#报告附件清理2026-11-01)
- [执行前审计汇总（附件已清理）](README.md#报告附件清理2026-11-01)

## 9. 实际执行记录

以下按实际顺序记录；各步只在原生任务和只读核验通过后记为成功。

### 9.1 执行前检查

预检通过：40 个目标缺失，已有主要指数 1 分钟 Raw 文件存在；两个日期分区已注册；相关 7 个 job 无活动任务，daemon 未运行；Lake 与 staging 同设备、可读写，空闲 2,716.38GiB，满足现有资金流 64GiB 门禁。[预检记录（附件已清理）](README.md#报告附件清理2026-11-01)。

开始按第 6 节命令串行执行。每个 job 完成后，只读该 run 的有界事件和本步文件事实，确认后再启动下一步。

### 9.2 主要指数 Raw

任务 `577aa308-cf0d-423c-ad24-d3ce3e6faab4` 成功，用时 9.75 秒，5 项检查全部通过且对应当前同日文件。已有 1 分钟 2,410 行经校验复用；新生成 5 分钟 490 行、15 分钟 170 行、30 分钟 90 行、60 分钟 50 行，共 800 行。[本步核验（附件已清理）](README.md#报告附件清理2026-11-01)。

### 9.3 主要指数 Silver

任务 `c56f057b-fa80-4698-b254-2bc372213615` 成功，用时 4.82 秒，7 个文件、7 项检查全部通过；原生五频共 3,210 行，90 分钟 30 行，120 分钟 20 行，合计 3,260 行。[本步核验（附件已清理）](README.md#报告附件清理2026-11-01)。

### 9.4 主要指数 Gold K 线

任务 `c3144419-17f4-4868-83a3-a01cd4eeeb0c` 成功，用时 2.84 秒，7 个文件共 3,220 行，7 项检查全部通过。非 1 分钟频率按现有 Gold 合同合并竞价锚点，因此不要求行数与 Silver 相同。[本步核验（附件已清理）](README.md#报告附件清理2026-11-01)。

### 9.5 主要指数分钟九转

任务 `553559fe-7703-4a2f-9fae-654adee79a23` 成功，用时 7.28 秒，6 个文件共 810 行，6 项检查全部通过。[本步核验（附件已清理）](README.md#报告附件清理2026-11-01)。

### 9.6 主要指数技术指标与状态

任务 `bcb58714-7ee0-43f5-8d0b-2214d70cd7f8` 成功，用时 10.18 秒，技术指标 7 个文件共 3,220 行，状态 7 个文件共 70 行，70 项检查全部通过且绑定当前同日物化。[本步核验（附件已清理）](README.md#报告附件清理2026-11-01)。至此主要指数原缺失的 38 项全部生成并通过检查，按管理员条件授权继续资金流 Raw → Silver。

### 9.7 THS 个股资金流 Raw

任务 `8e8c5892-7581-4bad-9ab1-1353d0363ff3` 成功，用时 76.4 秒，发布 5,218 行，原生 blocking file check 通过。源端两轮稳定性与数值合同检查通过，没有放宽 NaN 检查。[本步核验（附件已清理）](README.md#报告附件清理2026-11-01)。

资金流 Raw 实际请求 6 次、重试 0 次；两轮间隔 60.063 秒，两轮文件 hash 相同，行数均为 5,218。当前原生行数检查采用前五个日期参考值 5,216 行，本次未出现异常下降；该检查由原任务执行，没有追加独立历史深审计。

### 9.8 THS 个股资金流 Silver

任务 `b9a3a75e-71cd-410c-9be3-d8a16bf12ea2` 成功，用时 5.74 秒，发布 5,218 行，逐字段对账检查通过。Raw 日期保留源字符串，Silver 日期按现有合同归一化为 DATE，其余业务字段按合同对账。[本步核验（附件已清理）](README.md#报告附件清理2026-11-01)。

## 10. 最终结果

最终验收时间：2026-10-24 12:00:52（北京时间）。本次原缺失 40 项全部补齐：主要指数 38 项、THS 个股资金流 2 项，剩余缺失为 0。共新增 40 个文件，另校验复用已有主要指数 1 分钟 Raw 文件；7 个正式 job 全部 SUCCESS，没有失败、取消或重跑，41 项物化和 97 项不同检查目标全部通过。

| 范围 | 新增文件 | 最终文件行数（含复用） |
| --- | ---: | ---: |
| 主要指数 Raw | 4 | 3,210 |
| 主要指数 Silver | 7 | 3,260 |
| 主要指数 Gold | 7 | 3,220 |
| 主要指数分钟九转 | 6 | 810 |
| 主要指数技术指标 | 7 | 3,220 |
| 主要指数技术指标状态 | 7 | 70 |
| THS 个股资金流 Raw | 1 | 5,218 |
| THS 个股资金流 Silver | 1 | 5,218 |
| 合计 | 40 | 24,226 |

### 10.1 正式任务记录

| 顺序 | job | run_id | 检查数 | 任务耗时（秒） |
| --- | --- | --- | ---: | ---: |
| 1 | `raw_major_index_mins_update_job` | `577aa308-cf0d-423c-ad24-d3ce3e6faab4` | 5 | 9.75 |
| 2 | `silver_major_index_mins_update_job` | `c56f057b-fa80-4698-b254-2bc372213615` | 7 | 4.82 |
| 3 | `gold_major_index_mins_update_job` | `c3144419-17f4-4868-83a3-a01cd4eeeb0c` | 7 | 2.84 |
| 4 | `gold_major_index_mins_nineturn_update_job` | `553559fe-7703-4a2f-9fae-654adee79a23` | 6 | 7.28 |
| 5 | `gold_major_index_mins_technical_daily_update_job` | `bcb58714-7ee0-43f5-8d0b-2214d70cd7f8` | 70 | 10.18 |
| 6 | `raw_tushare_moneyflow_ths_update_job` | `8e8c5892-7581-4bad-9ab1-1353d0363ff3` | 1 | 76.40 |
| 7 | `silver_moneyflow_ths_update_job` | `b9a3a75e-71cd-410c-9be3-d8a16bf12ea2` | 1 | 5.74 |

### 10.2 最后验收与实际开销

- [最终读回](final-verified.json)：只对本次 41 个目标文件统一读回一次行数、schema 和压缩文件 hash；行数与当前物化 metadata 一致，schema 与当前 catalog 合同一致；有正式文件 hash metadata 的资金流文件也逐项匹配。原生检查全部绑定当前同日物化。
- 已有 1 分钟 Raw 的 hash 未改变，20/22 日同一范围共 82 个路径的存在性、大小和修改时间均未改变。相关 7 个 job 无活动任务，daemon 仍未运行。
- 正式执行源请求共 46 次：主要指数 40 次，资金流 6 次；重试 0 次。没有重复源端抽样或请求其它业务日期，也没有访问 Prod。资金流两轮各 5,218 行且 hash 相同，间隔 60.063 秒，原错误记录未再次触发非有限数值拒绝。
- 原生任务执行时间合计 117.008 秒；包括 CLI 装载、串行检查和操作记录的实际总时间 370.928 秒；最终文件读回 0.726 秒。41 个最终文件合计 1,598,868 字节。新增文件共 21,816 行；含复用文件共 24,226 行，不能把复用 2,410 行计为新增。
- 各步只读取本次 run 的有界事件以及必要文件状态，复用原生完整检查。最后没有重跑 159 项全局审计，没有重复执行公式或全文件差集。结合执行前 119 项有数据、本次 40 项缺失全部恢复，原审计范围的物理缺口已清零；未重新深审其余 119 项的数据质量。
- 本轮仅新增本报告目录、正式当天目标文件、运行 staging 和原生 DG 事件；没有修改 Python 业务代码、配置、原方案/LLD、sensor、daemon、cursor、动态分区或其它日期数据，没有安装依赖或提交 Git。
- CLI 提示当前未激活虚拟环境；实际命令始终使用项目已有 `.venv/bin/dg`，没有切换解释器或修改环境配置。该提示没有导致任务或检查失败。

[执行汇总（附件已清理）](README.md#报告附件清理2026-11-01)记录实际数量与耗时；[只读预检和核验脚本（附件已清理）](README.md#报告附件清理2026-11-01)仅作为操作证据归档，不接入 Definitions，也不启动任务或写正式数据。本轮没有新增或执行单元测试；验收依据是实际正式任务、97 项原生检查及限定范围的真实文件读回。文档完整性检查通过。
