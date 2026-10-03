# 新闻智能简报 M1 实施与验收记录

状态：**M1-0/M1-1/M1-2 已完成。旧教学集提交20条，旧盲标集提交0条。2026-10-03新版v3审核合同、表单、导入导出和10条真实预标注已实现并验证，新版教学集已导入10条，待用户试审；旧120条表单暂停。75项测试通过。M1-3、正式分类/摘要/排名质量及整窗性能仍未准入。**

依据：

- [新闻智能分类、摘要、排序与飞书推送方案 v1](/Users/congming/github/goldenshare/docs/architecture/news-intelligence-digest-feishu-plan-v1.md)
- [新闻智能分类、摘要、排序与飞书推送低层设计 v1](/Users/congming/github/goldenshare/docs/architecture/news-intelligence-digest-feishu-low-level-design-v1.md)
- [M0 测量与实机验证报告](/Users/congming/github/goldenshare/docs/architecture/news-intelligence-digest-feishu-m0-readonly-validation-2026-09-24.md)

## 1. 本切片目标与边界

本切片只提供历史离线回放所需的领域合同、三来源只读查询、确定性清洗、分层标签候选、保守聚类、抽样、评估、原子制品和模型进程安全适配器。

明确未做：数据库迁移、正式 Run/cursor/delivery 写入、现有 Wealth API/页面调整、常驻 Worker、飞书投递、模型微调和生产模型准入。

## 2. 硬口径映射

| 硬口径 | 实现位置 | 自动测试 |
|---|---|---|
| `news` 用 `news_time`、`major_news` 用 `pub_time` | `NewsIntelligenceReplaySourceQuery` | SQL 选择字段与窗口测试 |
| CCTV 只有内容日期，不伪造日内时间 | `stream_cctv_date`、`FrozenNewsItem` | CCTV 合同正反例 |
| PostgreSQL 查询事务必须只读 | `ensure_repeatable_read_only_transaction` | `SET TRANSACTION ... READ ONLY` 且每事务一次 |
| 不读取 `news.score` | 显式列查询 | 编译 SQL 负向断言 |
| 稳定 `sample_id`，内容变化由 `input_hash` 识别 | `freeze_news_item` | 稳定身份与内容变化测试 |
| 空内容和重复项不丢行 | `clean_candidate`、`mark_exact_duplicates` | reason code 与重复指向测试 |
| 默认短代表文本 128 tokens、模型端最大 512 | replay policy 与 model worker | 参数上限与代表文本测试 |
| 标签候选最多 4 个一级主题、6 个事件类型 | `build_label_candidates` | 上限与重点标签召回规则测试 |
| 语义聚类遇到时间/数字冲突不得合并 | `cluster_candidates` | 高相似但数字冲突负例 |
| 800 字且非单句才具备摘要资格 | `clean_candidate` | 800 字、短文、单句长文边界 |
| Top 30 / Top 15 和七维评分上限 | `ranking.py` | 七维完整性、分数上限与数量上限 |
| 三模型串行、Qwen 只绑定 loopback | `SerializedModelProcess`、`QwenLoopbackServer` | 超时清理、锁与非 loopback 拒绝 |
| 输出完整后同文件系统原子冻结 | `AtomicArtifactWriter` | 缺文件不发布、校验和篡改检测 |
| Argilla 保持 `sample_id/input_hash/taxonomy_version` | `argilla_exchange.py` | 导入导出身份往返测试 |
| v3辅助与独立任务物理分集，独立任务无建议 | `argilla_review.py`、`review_policy.py` | 独立字段/metadata白名单、接受/修改/未决、幂等与冲突测试；v2分集仅作历史证据 |
| Argilla 只允许 loopback，单实例最多1,000条 | `ArgillaHttpClient`、导入校验 | 非 loopback 与超限负向测试 |

## 3. 配置审计

M1 不新增生产 Settings 或远程环境变量。离线命令的显式参数和版本化代码策略如下：

| 配置 | 默认值 | 来源/持久化 | 作用域与消费者 | 生效与可见性 |
|---|---|---|---|---|
| `output_root` | `/data/disk/goldenshare/news-intelligence/m1` | CLI 参数 | 单次实验；Artifact Store | manifest 和命令行可见 |
| `model_root` | 无隐式默认 | 后续模型回放命令显式参数 | 单次模型进程 | 不写 Settings；启动时核验 |
| timezone / schedule | `Asia/Shanghai`；08/12/16/20/22 | 版本化 policy | Replay window builder | manifest 可见；边界测试 |
| source batch | 500 | query 构造参数 | 单次只读查询 | manifest 可见；必须为正数 |
| model limits | Embedding 1/512；NLI 16/512；Qwen 4 threads/1 parallel/2048 ctx | 版本化 model policy | 独立模型进程 | 只能调低；调高须重过 M0/M1 门禁 |
| deep analysis | 最大30 | 版本化 model policy | Qwen selector | M1 性能报告可建议调低 |
| summary | 800/12000 | 版本化 summary policy | 摘要选择器 | 边界测试；变更必须新版本 |
| Argilla API URL | `http://127.0.0.1:6900/api/v1` | CLI `--api-url`，版本化默认值 | M1 标注导入导出 | 仅 loopback；非本机 URL 直接拒绝 |
| Argilla credential | 无仓库默认密钥 | CLI `--api-key-file`；本机 `~/.config/goldenshare/news-intelligence/argilla/argilla_api_key`，权限0600 | 单次本机 CLI | 不打印密钥；不得写仓库或 Prod |
| Argilla workspace | `news-intelligence-m1` | CLI `--workspace`，版本化默认值 | 教学/盲标数据集 | 启动时要求唯一匹配 |
| Argilla dataset | `m1-taxonomy-v2-candidate-1-tutorial` / `m1-taxonomy-v2-candidate-1-blind` | 版本化代码常量与 Argilla PostgreSQL | 20条教学/120条盲标 | schema SHA-256 不一致时拒绝复用 |
| Argilla compose | `~/.config/goldenshare/news-intelligence/argilla/compose.yaml` | 本机私密运维目录 | Docker Desktop 当前本机用户 | 无仓库密钥；`docker compose ps` 可见 |
| Argilla 持久化 | Docker named volumes：PostgreSQL/OpenSearch/Redis/Argilla | Docker Desktop VM | 仅本机不超过1,000条临时标注任务 | 正式事实仍以 Prod HDD 版本化导出为准 |

## 4. 运行入口

生成试标包：

```bash
python -m src.scripts.news_intelligence_m1 prepare-pilot \
  --date YYYY-MM-DD \
  --experiment-id <immutable-id> \
  --output-root /data/disk/goldenshare/news-intelligence/m1
```

每个 `--date` 可重复。命令在一个 `REPEATABLE READ, READ ONLY` 快照中读取三来源，输出20条教学样本和120条盲标样本；如果任一来源无法满足40条盲标配额则失败，不生成不完整正式目录。

校验冻结目录：

```bash
python -m src.scripts.news_intelligence_m1 verify-artifacts <experiment-directory>
```

Embedding 和 mDeBERTa 已通过 `run-calibration-sample` 接入冻结试标样本的串行调度；Qwen loopback server、固定字段 Prompt、显式 GBNF 和应用侧 JSON 校验合同已经实现，但须在人工 taxonomy 试标后才能执行事实性与排名增益验收。当前不得把“适配器可运行”写成“模型或整窗已准入”。mDeBERTa 的 entailment/contradiction 索引从冻结模型 `config.json` 读取并校验；当前冻结制品实际为 `entailment=0/neutral=1/contradiction=2`，禁止硬编码常见但错误的索引顺序。多标签 zero-shot 分数按 [Transformers 官方 pipeline](https://github.com/huggingface/transformers/blob/main/src/transformers/pipelines/zero_shot_classification.py) 只对 contradiction/entailment logits 作二分归一化，不得把包含 neutral 的三分类 softmax 中 entailment 一列直接当成多标签概率。

模型样本回放：

```bash
python -m src.scripts.news_intelligence_m1 run-calibration-sample \
  --input-experiment <pilot-experiment-directory> \
  --experiment-id <immutable-id> \
  --model-root /data/disk/goldenshare/news-intelligence
```

该命令只处理冻结的20+120条样本，不会把六天全部原文送入模型。

本机 Argilla 导入：

```bash
python -m src.scripts.news_intelligence_m1 argilla-import \
  --input <pilot-experiment>/annotation_import.jsonl \
  --api-key-file ~/.config/goldenshare/news-intelligence/argilla/argilla_api_key
```

命令按 `sample_group` 分别写入教学集与盲标集；重复执行只核验 `external_id/input_hash/schema_sha256`，不重复建记录，也不会覆盖内容变化。盲标任务不导入模型 suggestions。已提交标注使用 `argilla-export` 导出到显式路径；导出只包含 `submitted` response，保留 `sample_id/input_hash/taxonomy_version/reviewer_id/annotation_round/submitted_at`，后续再把版本化结果写回 Prod HDD 冻结目录。

人工操作从 `http://127.0.0.1:6900` 登录，用户名为 `xiaoming0585`，密码只保存在本机0600私密文件 `~/.config/goldenshare/news-intelligence/argilla/argilla_password`。先完成 `m1-taxonomy-v2-candidate-1-tutorial` 的20条教学/讨论样本，确认理解一致后再开始 `m1-taxonomy-v2-candidate-1-blind` 的120条盲标。当前记录没有“候选新闻”和生成摘要，`same_event`、`summary_fact_check` 应选择“不适用”；不得凭空补造候选或摘要结论。

## 5. 当前验证

- M1、依赖矩阵和 legacy 护栏：49项通过；新增覆盖 loopback、教学/盲标分集、幂等导入、内容哈希冲突和只导出已提交标注。
- 现有新闻 DAO、页面去重、Wealth 新闻 API/Reader 回归：69项通过，只有既有 Starlette/httpx 弃用警告。
- 既有 M1 基线曾通过 Ruff；本轮现有虚拟环境未提供 Ruff，未自行安装依赖。新增代码已通过 `compileall` 和 `git diff --check`。
- 全仓测试：4,573项通过、10项跳过；当前沙箱禁止测试夹具绑定本机端口，导致345项本地 PostgreSQL类错误；另有33项非 M1 失败。`tests/news_intelligence/**` 无失败或错误，不能把该全仓结果表述为全绿。
- Prod 只读冻结实验：`m1-pilot-20260918-23-67185a66`，绑定 commit `67185a66`；`news=27,027`、`major_news=10,018`、`cctv_news=92`，共37,137条；来源内精确重复3,252条；试标导入包140条。完整制品为211 MiB，`SHA256SUMS` 复核通过，数据库事务为 `REPEATABLE READ, READ ONLY`。
- 首次模型回放 `m1-lightweight-pilot-25c08fb4` 暴露了 zero-shot 分数归一化错误：135个事件全部 `UNRESOLVED`。该制品保留为失败证据，不纳入质量评估。
- 修复后实验 `m1-lightweight-pilot-ec7b1cdf` 绑定 commit `ec7b1cdf`，`SHA256SUMS` 通过；140条候选形成135个事件，聚类规模为131个单条、3个两条、1个三条。临时阈值0.5下主题 `CLASSIFIED=95/UNRESOLVED=40`，事件类型 `CLASSIFIED=62/UNRESOLVED=21/NOT_APPLICABLE=52`；这些只证明推理语义已恢复，没有 gold label 前不构成准确率或阈值结论。
- 修复后140条轻量回放 wall-clock `511.34s`（约8.52分钟），主进程峰值 RSS `1,097,568 KiB`，模型子进程峰值 RSS `1,852,068 KiB`；结束后无模型进程、锁文件或监听端口残留。这是试标子集性能，不是最大整窗 `<60分钟` 准入证据。
- 2026-09-29 获得本机安装授权后，在当前 Docker Desktop 登录用户 `xiaoming0585` 的本机环境安装 Docker Desktop 4.93.0（Engine 29.8.1、Compose 5.5.1）；未向 Docker Hub 推送镜像、仓库或数据。
- Homebrew cask 因无交互 sudo 无法创建 `/usr/local/bin` 链接而回滚；随后使用 Homebrew 已校验下载的签名、notarized DMG 将 `Docker.app` 安装到 `/Applications`。CLI 使用当前用户目录 `~/.docker/bin`，未写系统级 CLI 链接，也没有 Homebrew cask receipt。
- Argilla 栈固定为以下多架构 manifest digest，本机实际拉取均为 `linux/arm64`：Argilla 2.8.0 `sha256:6f4af8fcf4b809d25aa88a6a4f8838dbacab9296c83b055a9a58f1db7526431a`，OpenSearch 2.18.0 `sha256:7f6fa1efee8f39e94ca30a0a31f95d866c8a99f25a86e6cf6691142d1eab4f9e`，PostgreSQL 14.17 `sha256:4836bc848e0d55e582f56d03f0ea89ee03fc33585cf46484f16233151613fd47`，Redis 7.4.2 `sha256:fbdbaea47b9ae4ecc2082ecdb4e1cea81e32176ffb1dcf643d422ad07427e5d9`。Argilla 只发布 `127.0.0.1:6900`，9200/5432/6379 均未发布到宿主机；遥测关闭。
- 合成冒烟数据集 `m1-deployment-smoke` 已完成登录、workspace、导入、提交标注、导出和整栈重启读回；重启前后 dataset/record ID 不变，证明 named volume 持久化有效，验收后已删除该合成集。初始化日志曾显示自动生成的 API key，已立即轮换；旧值失效，现有私密文件与数据库值一致。
- 冻结输入 `annotation_import.jsonl` 的 SHA-256 为 `4eab452317e98c88a4b8ed49cdd089c809a495e2acbdbab22c9f29fb6ce66f99`，共140条、140个唯一 `external_id`、140个有效 `input_hash`。正式教学集 ID `5f78d60f-3708-47d1-a308-8c1537687986` 已导入20条；盲标集 ID `295c93b8-f43f-473e-ac7a-25be6ab5972f` 已导入120条。第二次导入新增0条，当前两集已提交标注均为0。
- 正式140条任务导入后再次完成整栈重启，读回仍为教学20/盲标120且幂等新增0条；新增代码已通过49项聚焦测试。

## 6. 后续门禁

1. 保留旧20条教学标注，暂停旧120条盲标集；9月部署记录及旧命令仅是历史证据，不作为新版操作指导。
2. 依总体方案第8节及LLD 10.2.1实现新版审核合同，先真实预标注并导入10条演示；通过表单试审后再生成120条辅助审核。
3. 120条试审后间隔至少72小时做30条隐藏建议复标，报告单人自一致性及模型提示暴露局限；提交taxonomy review，通过后才生成正式800条。
4. 正式800条分600条辅助校准与200条独立验收。候选召回、Macro-F1与PR曲线正式门禁只能使用未参与调参的独立集，辅助接受率单列；临时0.5阈值尚未冻结。
5. 在 taxonomy 人工试标后完成 Qwen 摘要、事实核验和资源采样闭环。
6. 业务质量与最大窗口60分钟性能门禁未通过前不得进入M2。

### 6.1 本次修订执行约束（2026-10-03）

| 硬口径 | 实现落点 | 必须验证 |
| --- | --- | --- |
| 主题不混行业/关注标签，父子关系唯一 | Biz v3审核策略与主题选择器 | 父级停留、非法code、主副重复与祖先冲突 |
| 接受、局部修改、无法判断 | Biz审核结果归一化 | 无效预测不可接受；修改至少一项；未决必须原因 |
| 独立验收不显示建议 | App审核schema与导入器 | 盲标字段/metadata无预测，导出不得接受建议 |
| 预测必须原文证据与版本 | 预测构造器、审核导入导出 | 证据不在正文拒绝；sample_id/input_hash/版本稳定 |
| 旧标注不覆盖，10条先验 | 新版数据集与幂等校验 | 新名字；内容/预测冲突拒绝，不覆盖旧response |
| 独立集不能参与调参 | 正式抽样manifest与评估器 | 事件组隔离、角色过滤；暂未完成 |

本次 CodeGraph 分析覆盖审核schema、Argilla导入导出、Biz策略、M1脚本入口和测试消费者。改动保持App→Biz方向，不改变现有Wealth新闻API、页面去重、生产数据库或依赖矩阵。新表单只把原来分散的审核问题重组为合同，不新增移动端Debug或生产推送。

### 6.2 已实现与未实现（2026-10-03）

- Biz `review_policy.py`：唯一父路径、独立行业/关注标签、原文引文与模型revision校验、接受/修改/未决、独立任务禁止模型提示。
- App `argilla_review.py`：新版数据集schema、单一必答审核动作、清空标签操作、稳定身份与内容/预测冲突保护、建议/原始人工响应/最终结果分别导出。旧v2数据集和response不修改；旧命令只用于历史证据导出。
- M1新增显式命令 `argilla-review-import` / `argilla-review-export`。连接和凭据参数复用已审计的loopback合同，不增加端口、安装或生产Settings。
- `review_prelabel.py` / `review_demo.py`接入Prod冻结mDeBERTa：仅10条，规则缩小候选，主题最多4、事件类型最多6、二级最多3个同父候选；单模型串行。行业与关注标签为明示的字面规则，重要度保持UNKNOWN/NOT_ASSESSED，不冒充七维排名分析。CLI增加 `prepare-review-demo`。
- 聚焦测试新增26项；M1及三项架构护栏合计75项通过。
- 尚未完成：用户真实接受/修改/未决后的导出往返；行业定义与包含/排除示例细化；预标注质量纠偏、重要度预评、120条试审、30条复标和800条600/200事件隔离抽样。fake-only预测只在自动测试中使用，不导入用户工作台。

新版导入输入为JSONL，每条包含 `external_id`、`fields.title/content`、`metadata`（稳定身份、四个策略版本、`evaluation_role`、`prediction_exposed`）及辅助任务的 `machine_prediction`。预测必须含 `status=COMPLETE`、`prompt_version`、`model_revision`、九个审核字段值和逐字段原文引文/来源。COMPLETE只表示合同齐全，不表示准确、所有字段均已得出结论或已过质量门禁；UNKNOWN、UNRESOLVED必须保留。独立任务只允许原文和白名单身份/版本元数据，不含预测。导出路径必须不存在，避免覆盖旧审核事实；正式版本化导出仍需写回Prod HDD。

### 6.3 十条真实演示证据（2026-10-03）

- HDD实验：`/data/disk/goldenshare/news-intelligence/m1/m1-review-v3-demo-20261003`。输入沿用M1冻结文件，SHA-256 `4eab452317e98c88a4b8ed49cdd089c809a495e2acbdbab22c9f29fb6ce66f99`。未提交代码由manifest的 `code_tree_sha256=22e18d431aea34765c400bec935509deab997e2abf9cbd43be2a8d68a335eff4`识别，不能将基线commit当作已提交版本。
- 10条配额：news4、major_news3、cctv_news3。旧20条教学集实际无CCTV，因此CCTV3条取自原试标池；新角色全部TUTORIAL并标明预测已暴露，manifest保留原分组。它们永远不作为未受提示的独立验收样本，正式800条仍排除整个旧试标池。
- 真实NLI20个请求，总耗时69.85秒，子进程峰值RSS 1,296,152 KiB（约1.24GiB）。无Embedding/Qwen调用、数据库访问、正式业务表写入或消息发送。只输入标题/导语，不声称长文完整语义分析；原文完整呈现供审核。部分建议明显有待纠偏，临时0.5阈值不是准确率门槛。
- 本机数据集 `m1-taxonomy-v3-candidate-1-tutorial`，ID `ff72a42d-f8c9-43e0-8708-b4bf8bb2bd2a`，使用xiaoming0585工作区。首次导入10，重复导入新增0、已存在10；API读回验证内容及预测hash。当前无人工提交，真实导出为0条；接受/修改/未决全路径目前只有自动测试证据。浏览器当前未登录，尚未进行已登录界面核验；不得代替用户提交gold。
- Web/Ops运行前、期间、结束均active；结束pgrep无模型Worker/llama-server。vmstat期间/结束的一秒采样si/so均0，但宿主机既有swpd从1,159,724升至1,161,464 KiB。未采集全程进程级swap及服务p95，不能归因或宣称资源准入；后续性能试验必须补完整监测。
- 首次隔离打包被生产runtime包初始化导入阻断，模型未运行；已核查原因后使用不含生产runtime初始化的namespace工具包，不改变生产入口。实际工具目录为 `/data/disk/goldenshare/news-intelligence/m1/tooling-v3-review-20261003-ns`，初次失败目录留作诊断，不是实验事实。
- 下一步只请用户试审这10条。先核验表单是否能接受、局部改、清空和记录缺项；结合错误样本修订候选规则、定义和重要度预评，再扩展120条，不机械扩大当前未经校准的模型错误。

### 6.4 右侧原生预填修正（2026-10-03）

用户要求直接浏览右侧已选答案，而非依赖左侧文本。审计确认此前仅存机器建议文本与metadata，遗漏了Argilla原生Suggestions投影。依据本机2.8 OpenAPI与[官方审核指南](https://docs.argilla.io/latest/how_to_guides/annotate/#suggestions)，补充逐问题原生建议，文字证据保留。界面应使用Focus单条审核，批量视图不显示此类建议。

- `argilla_review.py`在导入/幂等重跑后补充Suggestions：只投影非空预测，保留原文、预测和身份hash；不预填review_action、不创建人工response，已有draft/submitted则跳过。冲突不覆盖，先完整审计再逐项PUT并GET验证。
- 实机首次写入遇到空多选422，核查后按当前版本约束跳过空列表，不补造NONE分类；幂等续跑保留已写项。现有10条共有61个原生Suggestions，review_action建议0，人工responses仍0。没有重跑模型或改正式HDD实验。
- `review_policy.py`允许ACCEPT提交与机器答案一致的预填值；EDIT按差异记录，不能把未改动的预填值算成人工纠偏。人工原始提交仍完整导出。
- 新增草稿保护、建议冲突及独立无建议测试，补充完整预填接受/修改测试；M1与三项架构护栏合计78项通过。CodeGraph query/impact覆盖Biz归一化、App导入导出、演示生成器、CLI和测试；不改变生产API与依赖矩阵。
- API读回确认建议已关联问题；本轮没有已登录界面的视觉核验或代替用户提交。请刷新现有教学集Focus界面试审。原有模型质量、重要度和M1准入限制不变。
