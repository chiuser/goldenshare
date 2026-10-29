# 28日原readback适配说明（准备结果，不是真实验收）

依据：原合并方案/LLD§17.3/17.5/17.6，以及23日batch9/10原readback.py.txt。按根代理确认，旧preflight/control/prepare入口不适用，未保留可误调入口；没有运行旧preflight或任何正式读回。

## 文件和差异

- `qfq_factor_readback_20261028.py`：来自23日batch9。保留16个原验收函数，函数源码逐字节相同。删除旧`run_preflight`及其CLI路由、`--predecessor-dir`；CLI只允许daily/factor。
- `macd_readback_20261028.py`：来自23日batch10。保留17个原验收函数（包括完整`verify_run`），函数源码逐字节相同。删除`_control_load/_control_save/_control_open/_control_quiet/_control_upstream_receipts/_control_scope_baseline/run_preflight/prepare_repair/final_control`；薄CLI只允许daily/repair并调用原verify_run。
- `readback-adaptation.diff`：原档案与适配文件的完整unified diff。
- `readback-adaptation-summary.json`：原文件/适配文件SHA256、每个保留函数、移除函数及替换表。
- `check_readback_adaptation.py`、`readback-static-checks.json`：静态及人工合成输入验证；不import完整适配模块，不连接DB、不读取Lake、不求值真实guard。

字面替换仅包括：`DAY/B10_DAY: 2026-10-23 → 2026-10-28`；报告根`datasets_recovery_20261023_20261026 → datasets_recovery_20261028_20261029`；一条报告目录错误提示由23-day改成28-day。batch9/batch10子目录名称、原job/asset/check名称、正式Lake/staging和原compute log根不变。保留函数没有固定22日前序日期；旧22日路径只存在已删除的旧preflight，本轮27日前序由根代理真实preflight提供。

33个保留函数的当前源码与原档案逐字节一致；没有修改股票名单、日期数、文件数、batch/hash、guard、receipt、scope或绑定规则。只删除不适用的编排入口并修改最外层CLI，未加入业务计算或写入入口。

## 正式使用前由根代理提供的真实材料

1. 本轮原job真实run id、root id，以及其真实compute stdout。脚本不启动job。
2. batch9的真实输入身份manifest。原接口允许未传manifest时生成不完整结果；本轮必须传`--input-manifest`并要求`verified=true`、`input_identity_complete=true`、`stage_acceptance_complete=true`。不能把仅事件通过当成完整验收。
3. batch10/preflight.json：必须由当前§17前序核验产生，至少含`safe_to_launch=true`与原factor guard真实`factor_gate`。脚本不会自行构造，也不能复制23日文件；真实factor当前身份将与其中producer/batch/起止/名单/hash/事件IDs逐项对照。
4. MACD repair前须已有本轮batch10/daily-run-verified.json和原decision/config函数产生的repair-run-config.json。原verify_run会核同一batch、原配置、完整14条completion及完整repair gate。
5. batch10真实日志仅接受`/Users/congming/.goldenshare/dagster_logs/<精确run_id>/compute_logs/*.out`；默认会在该精确run目录取原stdout。归档报告中的compute.out不能代替该来源保护。

## 计划调用方式（未执行）

工作目录为orchestrator，沿现有`.venv`及正式DAGSTER_HOME。根代理先用GraphQL启动原job、等待终态；以下只用于验收。`<...>`全部须替换为本次真实产物，不能照填旧run。

```text
.venv/bin/python3 -B /private/tmp/dg_minute_chain_20261028_20261029/qfq_factor_readback_20261028.py --mode daily --run-id <QFQ真实run> --report-dir <本轮报告根>/batch9 --log <本run原stdout> --input-manifest <本轮真实输入manifest>
.venv/bin/python3 -B /private/tmp/dg_minute_chain_20261028_20261029/qfq_factor_readback_20261028.py --mode factor --run-id <原因子真实run> --report-dir <本轮报告根>/batch9 --log <本run原stdout> --input-manifest <本轮真实输入manifest>
.venv/bin/python3 -B /private/tmp/dg_minute_chain_20261028_20261029/macd_readback_20261028.py --mode daily --run-id <MACD日更真实run>
.venv/bin/python3 -B /private/tmp/dg_minute_chain_20261028_20261029/macd_readback_20261028.py --mode repair --run-id <MACD历史repair真实run>
```

本轮报告根为`/Users/congming/github/goldenshare/lake_console/reports/datasets_recovery_20261028_20261029`。两个适配文件只把验收JSON写入该根，读取原控制记录/日志/receipt和stat，不打开Parquet、不重新计算摘要或价格、不写事件。readonly PG会话及`should_autocreate_tables=False`保持原样。

daily必须在后续repair之前保存验收。repair合法覆盖的年度/state最终身份按后写入repair回执，不能用daily旧stat否定新结果。MACD原verify_run对同run已完成的daily验收直接复用，避免repair后再次stat旧daily；根代理完成最终重叠目标交接对账，不运行已删除的旧final_control。

## 准备验证及局限

20项静态/合成检查全部通过：两份语法与禁止操作检查、两份保留函数逐字节比对、4个旧CLI模式拒绝、两组人工事件字典正例及错日/缺物化/缺检查/失败检查/错物化绑定反例。人工catalog只用于证明绑定/日期断言仍工作，不冒充真实catalog或源合同验收。

验证期间正式DB连接0、Lake调用0、真实guard求值0、真实run验收0、Parquet读取0、数据SHA读取0。仅在/tmp写入准备文件和小型结果；未运行完整适配模块，未启动job或sensor。初版合成检查器遗漏argparse命名空间后报NameError，已修正检查器并完整重跑；适配验收函数没有因此修改。
