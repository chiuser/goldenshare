# Foundation读取修复：3项配套测试问题收尾

本轮先补原方案和LLD的`locator-test-cleanup-20261028`，再只修改配套测试。两份已有生产修复保持原验收SHA，不再改算法、数据范围或异常合同；与测试、原两文、旧定位证据和本轮证据一起按明确白名单提交。

## 3项修正

1. **普通pytest不再受旧验收状态限制。** 删除`_REPORT/_STARTED`、历史plan/resume/failed_setup读取及旧累计。`_State`从当前测试的0计量开始，`save()`只更新内存，不把旧`progress=passed`当作回归失败原因。测试计时从各自State创建开始作说明，本轮程序时间限制在外部执行记录管理。
2. **普通pytest不再改写旧验收文件。** 原`progress.json`写入移除，指标经pytest的JUnit property交给外部本轮记录。每个测试在自身作用域禁止读取/写入仓库reports下的Path.read_text/write_text；原68份历史文件集合与SHA在执行前后均不变。
3. **三个测试不再依赖顺序。** 每个函数获得独立State和临时目录。前两项各准备原3根字面样本，第三项只创建State，不读价格/不执行SQL；原`7/10/59`全组断言改为各函数独立的调用数和费用断言。旧7/10/59含当时失败1行，仍保留在旧报告，不混入本轮。

没有仅删除断言来迎合实现。原请求、价格/日期/schema、prepare SQL、故障注入方法及所有正常结果、异常类型、cause、故障前真实交付、句柄关闭、注册/表/输入流和唯一连接释放检查均保留；AST已逐项与保存的原测试核对。原`run`只增加控制替身创建计数。已有SourceReadError/取消/到期/KeyboardInterrupt/ValueError仍保持同一对象和无cause。

## 唯一验证清单和实际费用

3项各在独立pytest进程执行一次，顺序刻意先运行原来的第三项，未重复或运行整组：

| 顺序 | 原测试函数 | 结果 | 输入，含临时数据 | 定位 | SQL逻辑行 | D3Control替身 |
|---|---|---|---:|---:|---:|---:|
| 1 | test_locator_preserves_existing_errors | passed | 0 | 0 | 0 | 5 |
| 2 | test_locator_metadata_memory_and_close_errors | passed | 3 | 5 | 11 | 3 |
| 3 | test_locator_read_errors_and_cleanup | passed | 6 | 5 | 50 | 4 |
| 合计 | 3函数，各一次 | passed | 9 | 10 | 61 | 12 |

真实ExecutionControl新增0；7次原calculate仍使用D3Control计时/停止替身，真实本地Parquet/Arrow/DuckDB计算和清理保留，不构成正式Lake或新D4验收。2份临时来源各3根，正常价格读取3根；SQL61=服务48+关闭拒绝探针7+两次临时COPY共6。未创建新参考、长样本或参数矩阵。

3项实际费用均与预先独立推导一致。第三项先单独通过、无文件准备且0/0/0，直接验证不依赖前两项；每个函数的fixture都已实际删除自己的临时目录。清理失败也会在finally交付JUnit计量并继续报错；没有把失败伪装成功。

外部执行禁用自动插件，使用精确nodeid、`-x`、无cache、`junit_family=xunit1`。无祖先conftest。本轮单程序30秒、总60秒，失败停止、无自动重跑；实际累计见progress/acceptance。未重跑D1/D2/D3/D4、旧缺陷探针或任何其它测试。

## 静态审计与文档

- CodeGraph核对fixture名称及当前源码消费者。pytest动态fixture调用不能仅靠调用图确定，已读取原3函数及全部辅助逻辑确认。
- Context7核对pytest函数fixture/yield清理和monkeypatch恢复，再结合已有D4的xunit1计量方法复用。
- 独立只读预审和执行后核对确认计量、错误原对象、旧68文件及生产2文件指纹、3个目录删除均正确，没有额外测试或SQL。
- 原方案、LLD完成状态和19.34历史说明同步，原一次性续跑门禁保留为历史，不继续指导日常测试。
- 文档收尾第一次标题定位只接受h2/h3 id，而组件文档id在section上，写入前断言停止。已记录`closeout_document_attempt_01.json`；按两文现有结构更正定位后更新。未修改测试、生产代码或旧证据，没有任何测试重跑。

## 提交与范围

白名单为两份原生产修复、一个配套测试、原两份HTML、原定位16份证据及本轮新目录。提交前核暂存文件集合、空白和文档完整性，保留其它工作区修改，不推送或部署。

本轮关闭的是此前“Git版本与已验收来源版本不一致”的收尾问题；不是新的业务阶段。正式API/页面接入方案与LLD、业务迁移及DG任务退出仍在后续，本轮未启动。

## 原始日志的格式保留

首次暂存全体空白检查只发现旧定位`pytest_output.txt`第15、16、42行原始行尾空格。该日志属于不可改写的旧证据，保留原字节；单独核对其磁盘/暂存/旧SHA一致，其余所有白名单文件严格检查空白。此唯一例外已先补回原方案、LLD与plan，不修改任何代码断言、Git配置或attributes，不重跑测试。
