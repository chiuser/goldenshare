# D3 第二轮独立只读核验：要求与测试所经层次

核验工作区：`/Users/congming/github/goldenshare`，分支 `dev-interface`，HEAD `e591b7eca`。仅阅读代码、两份 HTML 原文、测试和保存报告；未运行 pytest、SQL、项目导入、正式数据查询，未修改仓库文件。

## 结论

没有确认新的产品实现错误。发现一项仍有效 D3 硬规则的反向验收证据不足，提交主审判断：最终结果实际取回数量与 COUNT 不符或超过上限时必须整次失败；现有缺行测试在更早的 append 检查阶段失败，不能证明最终读取检查有效。

## 需主审判定的验收缺口

### 最终读取数量错误尚未触发过

- 原要求：`docs/architecture/technical-indicator-kernel-low-level-design-v1.html:1563-1564`（14.5）明确累计取回超过 `max_rows` 立即报 `OutputContractError`；最终取回数量与表实际 COUNT 不符也必须整次失败，不能截断成功。`2423-2424`（19.10）继续要求完整读取数量核对和明确原因，`2473-2474`要求在既定小样本注入结果错误并整次失败；19.22、19.25、19.29未撤回这条规则。根 AGENTS“按计划开发执行链”第3条要求硬口径具有正反测试。
- 当前实现：`src/foundation/technical_indicators/executor.py:255-260` 拒绝超过 max_rows；`src/foundation/technical_indicators/output/collector.py:365-381`先查 COUNT，并在最终 fetch 数量不符时抛 `fetch_count_mismatch`。
- 现有测试实际经过的层：`tests/foundation/technical_indicators/test_d3_output_failures.py:39-62`先正常计算，再在 `CalculationEngine.output_for`中删除 seq=2，随后被 Collector append 阶段的 `check_batch_rows`拒绝，未执行最终 COUNT/fetch。`141-199`直接测试执行器，正常真实3行、max_rows=3，每次1行并要求4次fetch；反例只在第二次fetch抛 OSError并核 `OutputReadError/fetch_failed`（183-186），没有提前空返回或超过3行。
- 全局检查：本库测试所有 `read_result`调用仅上述178/184及扩展测试196（真实3行、max_rows=3正常）三处；没有 `fetch_count_mismatch`断言或最终 COUNT/fetch差异注入。保存 `progress.json`中25次call及所有 executed_cases也没有该错误，原有20+6+1项通过记录没有覆盖此路径。
- 影响：目前不能以“append缺行拒绝”或“短fetch继续”证明“最后取回不完整仍拒绝成功”。这是一项验收证据缺口，不是已经证明实现会错误成功；也不要求穷举全部 reason 或增加长数据/真实控制请求。
- 建议：若主审认定需闭合，只补本条既定数量检查的小反例及正常对照；先落回原方案/LLD后再执行，不重跑通过场景、不改产品以迎合测试。本轮没有补测。

## 已核实的覆盖

| D3有效要求组 | 实际测试与证据 |
| --- | --- |
| 10001根首组合与9001根向前页、8192满批/尾批、MA/BOLL依赖复用 | `test_history_and_paging.py:56-86`真实 calculate、真实控制对象两次；独立逐字段参考、时间/页边界、14次rolling_mean、第二批MACD历史不重递推；保存首轮11通过和续轮9通过日志 |
| 三套真实MACD参数与数学安全分段 | `test_smoothing_boundaries.py:14-42`真实算法SQL、2051根同源、三套独立HUGEINT参考、首根9字段严格0，控制时钟替身范围明确 |
| 初始NULL、MA N=1及大周期、BOLL总体方差/倍率0与11、MACD字面与signal=1 | `test_indicator_literals.py:14-56`，独立3根字面；没有重跑旧人为长矩阵 |
| 日线多文件合批、一次qfq与量额不变、短历史保留行 | `test_batch_lifecycle.py:16-36`21份文件变一次21行指标批；MA20前19 NULL及后两字面值 |
| 两种合法空结果与当前周更新 | `test_empty_results.py:15-45`两次真实控制完整服务；48-86两次单周值更新保留一根/实际截止；周线原失败及修复续跑均保留 |
| SQL不可表示单分量不能被MIN忽略 | `test_d3_required_acceptance.py:27-51`真实参数SQL、零价格读取、明确两步4逻辑行、RequestInvalidError、无清理附记 |
| 输出说明隔离、读取范围非法/未知global日期 | 同文件54-161，直接构造/normalize/build的层次与19.25批准范围一致；未拿旧不可变对象测试替代 |
| 新Calculation经过原Engine、KDJ非50首根及K=1/D=1、旧批拒绝 | `test_d3_engine_extension.py:117-242`真实Engine与固定SQL、3根独立字面，旧批在SQL前拒绝且统计不变；未拿D1手调prepare/consume冒充 |
| 模板请求内一次/跨请求重新读取、只读映射、越界清单、部分加载停止与重复清理 | 首组合/前页模板次数；`test_d3_output_failures.py:202-287`；`test_d3_engine_extension.py:245-351`；对应07.5/19.22/19.25 |
| 直接calculate UTF8少于/等于/超过限制与统一清理（前F1） | `test_d3_calculate_output_bytes.py:22-207`内部3次真实calculate、独立完整JSON1205字节、1206/1205成功、1204原ResourceLimitError且未成功；每次实际查询已关闭连接并核ConnectionException、表/Arrow空、cleanup_ready、资源释放时间；保存单函数1通过及明细 |
| 原暂停标题（前F2） | LLD2658已标历史，并链接19.28/19.29；没有重复报旧问题 |
| 7份计算+3份输出SQL及源码包声明、Foundation边界及输出不识别plan | `tests/architecture/test_technical_indicator_dependencies.py:11-80`的实际断言；没有把源码清单当wheel安装证明 |

## 保存证据与当前文件的一致性

读取 `calculate_output_bytes_baseline_20261026.json`的66份保护文件SHA256逐一与当前文件比较，无不符；独立参考JSON SHA256仍为 `b06fdd4ba4e01f3a86a0fa110cdc1f375fd1cd1a2b3d7e8aa80df9685573c1a4`。

原始日志保留：初轮11通过/1失败、续轮9通过、补验6通过、字节小验收1通过。当前累计输入21139、SQL逻辑1324859、真实Control4、含失败的程序累计18.977130916900933秒。字节验收临时目录记录为已移除、无清理错误。上述均为读取保存证据，不代表本轮重新运行验证。

## 明确排除

D4并发/等待、RSS/全容量/低内存、完整真实取消和ASGI，正式API/页面/XXM迁移、DG退出、wheel构建安装均不作为本次D3缺项。19.10已替代的旧参数/分批大矩阵未恢复为验收要求。未核正式行情质量或正式数据。
