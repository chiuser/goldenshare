# Goldenshare Documentation Garden Report：A组产品代码级LLD审计

日期：2026-10-16。范围仅上证日线和60／90／120分钟的同段结构消失／重新钝化；用户授权补齐LLD并审计开发准备度，本轮不改产品或研究代码。

**结论：技术上具备按限定方案进入开发的条件；用户确认[原LLD§21](../../wealth/docs/pages/index-detail/index-detail-xxm-implementation-and-low-level-design-v0.1.md#xxm-same-segment-a1-code-lld)后可开工。** 本轮完成设计缺口的代码级定义，未把拟议合同写进产品；正式预算、接口迁移、页面与软件唯一公式仍未验收。

## Scope

原算法方案、识别LLD和技术面预测方案；直接审计当前h1代码、严格DTO、query／cache／snapshot、预测完整域、Wealth客户端与图层／文案消费者，以及现行测试。没有创建新主方案或索引系统。

## Authority and Evidence

当前行为以磁盘源码为准，工作规则以用户辨认和原方案§12.12为准；研究证据是`xxm_same_segment_precheck_20261016_04`，它未证明原软件唯一公式或正式4秒预算。CodeGraph explore／impact覆盖XxmCalculator、SeriesEntry、预测和Wealth，impact返回80个相关符号，包含研究及测试，不能视为80个产品消费者。动态装配、两个图表入口和前端白名单由当前源码补核。

## Findings

### G1：研究通过尚不能替代产品合同

- Document：识别LLD§15、§20；原方案§12.12。
- Evidence checked：calculator.step／snapshot／restore、types、query_service.SeriesEntry／_response及两schema。
- Finding：旧§15无条件等待草案已失败；新研究没有产品等待账本、窗口外关联、严格快照／as-of与单一新版身份迁移。
- Impact：直接照旧草案编码会漏8/22；仅搬研究分支会被DTO拒绝或泄漏未来结束状态。
- Suggested action：在原LLD新增§21，冻结产品字段、执行次序、真实调用链及正反例门禁，明确覆盖旧草案。
- Human confirmation required：是，产品合同及工作假设需用户确认；补文档已获授权。
- Design disposition：已在§21.2—21.6、21.8补齐字段、函数、快照／窗口投影和唯一版本；旧§15明确作废，未实施。

### G1：预测入口、完整域和文案必须共同迁移

- Document：预测方案§25、识别LLD§15.4。
- Evidence checked：forecast_query_service.build、forecast_entry、forecast_detector、forecast_joint、forecast_text、ForecastResponseDto、adaptForecast。
- Finding：当前activation_signature只接受activation；区间资格使用累计极值；query从历史找最近结构；前端未知根字段拒绝。不能仅更改卡片文案。
- Impact：等待被当首次激活，旧结构被误报仍有效，或新响应无法显示。
- Suggested action：明确固定参照重入分区、真实结构关联、rearmContext、后端display及所有严格白名单。
- Human confirmation required：是，作为§21完整迁移合同统一确认。
- Design disposition：已在§21.7定义每个数学／query函数及context／后端display；预测方案§26和文首状态同步，旧失败记录保留。

### G1：临时候选对旧h1源码有导入依赖

- Document：研究README及识别LLD§20.2。
- Evidence checked：same_segment_candidate._isolated_step、same_segment_precheck、test_xxm_same_segment_research。
- Finding：候选按原step精确源码片段编译；升级正式step后该片段不再存在，旧研究模块将导入失败。
- Impact：若原样保留活跃入口，主题测试和“当前运行命令”失效；不能用第二在线内核维持它。
- Suggested action：新交付目录封存当前候选源码／哈希及h1依赖版本；正反例迁入正式测试，原runner改为正式验收入口，候选及仅为隔离绑定而设的测试清退，先做引用清零。
- Human confirmation required：是，包含在本轮拟议文件清单；本轮不清退源码。
- Design disposition：已在§21.10明确前置源码封存、正式测试迁移、runner改名和引用清零；不保留旧引擎兼容入口。

### G2：研究私有结构ID不宜机械搬进正式内核

- Document：识别LLD§20及新§21.3。
- Evidence checked：现有pending_bottom_history、研究_start_rearm及冻结三门槛四周期[锚点核查](./anchor_audit.json)。
- Finding：研究用额外_current_structure_id挂接旧h1，但正式内核创建等待时已有未离段的B记录可提供原结构锚点。
- Impact：重复保存两个结构身份易漂移，且会扩大snapshot合同。
- Suggested action：直接从B记录深拷贝元数据到等待，再结束原B；不新增长期active_structure_id。
- Human confirmation required：包含在§21统一设计评审，不需要新软件材料。
- Design disposition：39747根×三门槛核查相容，§21.3—21.5明确不变量；仍须新实现T01—T06验证。

## Checks Run

已完成静态调用链与字段审计，读取原研究run／summary／verification并核源码SHA。CodeGraph explore／impact前置，结束sync／status正常；补核两个图表入口、真实API和严格前端消费者，无依赖矩阵变化。

当前h1隔离测试125项通过（42.87秒），覆盖两组真实FastAPI路由／query／内核／DTO及shared loads，使用SQLite内存库／临时Parquet，未连正式数据库或Lake。日志见[current_api_tests.log](./current_api_tests.log)；一条现有Starlette/httpx弃用提示不影响结果，未安装或升级依赖。不是a1新合同通过。

另以同一已批准候选2核查四周期三门槛的B锚点及等待快照前提，见[anchor_audit.json](./anchor_audit.json)，没有新增规则或改数值门槛。文档完整性、范围空白检查通过；最终链接和保护清单详见[verification.json](./verification.json)。

## Checks Not Run

本轮不运行正式源、真实网络HTTP性能、整页／多标签、前端typecheck／build或浏览器；页面由用户人工验收。未改UI代码，本轮前端验证是静态合同审计。研究既有63项及369组成绩只是上轮证据，不能列作本轮新内核验收。

## Maintenance Suggestions

保留原路径、失败候选和旧验收证据；新§21成为A组产品迁移的唯一代码级入口，算法规则仍以原方案为准，预测文档只补本域映射。

已更新原算法方案文首／§12.12和末尾核心表引导、原识别LLD§21、原预测方案文首／§26；没有新建主方案、改docs索引、触碰未授权脏文件或此前标注修复。§21含A01—A10、T01—T15、A1—A4里程碑、通用清单2.1—2.18及八原则映射和两条来源未变化的例外。下一步是用户确认后按里程碑实施，不需要继续盲找截图。

## Residual Risk

精确反向门槛、OHLC、软件通用历史寿命和顶部疑报仍未知；两处未有软件真值的90分钟历史差异需明示，不据此阻断已有候选的有限实施，也不宣称已完全复刻。
