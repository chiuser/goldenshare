# 新闻智能简报 M1 实施与验收记录

状态：**M1-0/M1-1/M1-2 已完成；M1-3 的本机 Argilla 2.8.0 + OpenSearch 2.18.0 已部署并通过导入、标注、导出和重启持久化冒烟测试，20条教学样本与120条盲标样本已分别导入。人工标注尚未开始，M1-3 尚未完成；分类质量、摘要、排名和整窗性能仍未准入。**

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
| 教学样本与盲标样本物理分集且不携带模型建议 | `argilla_workspace.py` | 分集、幂等导入与无 suggestions 测试 |
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

1. 先在教学集完成20条讨论标注，再完成120条盲标；不得把合成冒烟标注计入人工指标。
2. 完成教学与盲标后停止，由用户评审 taxonomy；未确认前不生成800条正式集。
3. taxonomy 评审通过后，间隔至少72小时从盲标集中打乱抽取30条做同一标注者复标；不得表述为标注员间一致性。
4. 人工 gold label 导出后才能计算候选召回、Macro-F1 与 PR 曲线，并据此调整当前临时0.5阈值。
5. 在 taxonomy 人工试标后完成 Qwen 摘要、事实核验和资源采样闭环。
6. 业务质量与最大窗口60分钟性能门禁未通过前不得进入M2。
