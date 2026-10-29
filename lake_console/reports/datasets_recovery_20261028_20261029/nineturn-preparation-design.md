# 28日九转临时入口的准备口径

依据：原方案/LLD§17.3、§17.5、§17.6与23日batch11执行卡、readback.py.txt。只准备脚本和静态验证，未连接正式服务、未读取或stat正式Lake、未触发job/sensor。正式运行由根代理复核后执行。

## 入口及范围

- `metadata`：承接本轮factor、MACD daily及必要repair真实验收和当前原guard；只读控制记录、精确27日九转run `459146ff-d2b1-479c-8c4a-5fbdab04e55a` 的四物化/四检查、原publication JSON和文件stat，形成27日seed依据。不存在专门旧归档，不能复制22日旧报告。保留原schema、行数一致、公式版本、检查物化绑定、receipt/stat、当前最新物化身份保护；不重新计算27日指标。核五sensor停止、相关writer/pool空闲、前序分区、同设备及空间；不要求daemon停止。枚举正常两年来源和实际因子名单的ALL year=*，范围外年立即拒绝。
- `prepare`：先运行原有界候选键查询，限定正常2025/2026输入及27日seed；随后对真实候选ALL year=* stat。将seed历史和候选的全部2014—2026文件按路径去重，合计必须≤1GiB，包含2025/2026候选文件；正常全市场两年来源另计。全部通过再进行必要的一次seed比较。报告`all_history_bytes`，另保留`older_bytes`作为早于2025年的诊断，不能只拿后者判预算。比较沿原完整历史公式后筛27日末根，不预先截断输入；不改名单、原公式或正式planner，不调用fallback历史查询。候选正常键查询和最终job的重复键查询已纳入原预算。
- `before`：刷新真实gate、五sensor、writer/pool、输入stat和目标仍不存在；生成batch11/preflight.json给既有薄触发器。脚本不触发job，不使用旧dg launch、discover或daemon控制入口。已有candidate-scope保留，不自动重复已执行查询。
- `verify --run-id`：必须与薄触发器保存的本轮daily-native-run.json、daily-launch-intent.json一致；保留原28日四物化/四原检查、来源计数、完整绑定、publication/receipt/stat、输入及27/29日邻居未变保护。输出final-verified.json，不重新读Parquet、计算SHA、重跑check或写事件。

## 实现对应与失败

原`compare_sql`、`historical_paths`、`guard_group`、`complete_inputs`、事件/receipt断言均复用；日期和报告根替换为28/27/29。正常28日验收仍用本轮原候选查询的真实每频行数，不能从物化自己产生预期。27日旧seed只验证既有物化/检查及receipt的一致性，明确不声称本轮重新核过其源行情；必要历史seed公式核验单独记录。

真实guard/config由现成job产生，所有名单/hash/batch/日期与当前保存报告逐项一致。无历史改写时不要求虚构MACD repair；有历史改写时必须有真实repair通过及完整gate。任何差异、越界、缺失或查询异常均保存阶段并停止，不自动重读或触发job。临时入口只写本轮batch11小报告，无正式Lake/staging/DB写入，也不安装依赖、修改资源/并发或施加job限额。

预算继续沿本轮已批准九转26GiB读/3GiB写/3GiB额外空间，包含候选准备、一次必要seed比较、原job/原检查及最后stat；不是运行上限。中断后先核真实记录，不自动重跑。准备验证仅AST、独立字面事件和路径夹具，不把合成结果当成真实来源验收；夹具及隔离目录结束删除，保留小型代码/差异/结果报告供复核。

## 准备结果与后续调用

入口：`nineturn_readback_20261028.py`。生成依据与差异保存在`build_nineturn_readback.py`、`nineturn-readback-adaptation.diff`、`nineturn-readback-adaptation-summary.json`。23个原函数逐字节保留，仅两处旧日期文字/注释改为当前含义；其中28日`verify_events`和`verify_publications`断言完全未改。27日精确旧seed采用同组断言的显式变体：日期改为27日、核当前最新物化身份，旧来源行数只做现有metadata/check/receipt一致性核对，不要求新28日启动窗口或旧文件before为空，不声称重新计数过27日行情。必要的实际变化股seed公式比较另在prepare执行。

`check_nineturn_preparation.py`运行30项AST/字面隔离检查全部通过，结果为`nineturn-preparation-static-checks.json`。覆盖23函数保留、无启动/daemon/fallback入口、ALL year=*拒绝2013、seed/候选路径去重及1GiB越界、2026候选单独超1GiB拒绝且不读历史、2026计入总量而`older_bytes=0`、原公式先完整计算后筛27日、28日与27日事件/check绑定、错误日期/行数/公式/缺检查/错run拒绝、原publication与27日已有before路径、receipt身份/行数错误拒绝、候选/stat完成后才核seed、无历史变化不核seed、越界不读历史、seed差异停止及任何阶段不自动重做prepare。实际网络/DB/正式Lake读取和stat均为0，生产模块import为0，全部临时夹具已删除。

正式使用前，根代理先确认前四步的本轮真实验收已完成，并复核脚本；下列仅为计划命令，准备阶段未执行：

```text
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python3 -B /private/tmp/dg_minute_chain_20261028_20261029/nineturn_readback_20261028.py metadata
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python3 -B /private/tmp/dg_minute_chain_20261028_20261029/nineturn_readback_20261028.py prepare
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python3 -B /private/tmp/dg_minute_chain_20261028_20261029/nineturn_readback_20261028.py before
```

工作目录为现有orchestrator。`before`生成真实`batch11/preflight.json`后，由既有`run_original_job.py --stage nineturn`提交唯一原job。该job成功后用同一前缀执行`nineturn_readback_20261028.py verify --run-id <本轮真实run>`。不运行旧discover或dg launch。输入固定为本轮`batch9/factor-run-verified.json`、`batch10/daily-run-verified.json`及必要的`batch10/repair-run-verified.json`，各自绑定本轮native-run；28日历史批准从本轮`history-approval.json`读取。目录和readback输出不能预填假的通过值。

没有调用真实builder、guard、公式或job；未完成真实源接入与正式验收。上述准备通过仅说明当前辅助入口保留并能执行约定的拒绝检查。
