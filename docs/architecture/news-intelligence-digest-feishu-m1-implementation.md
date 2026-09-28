# 新闻智能简报 M1 实施与验收记录

状态：**M1-0/M1-1 已完成；M1-2 已在 Prod HDD 对冻结的20+120条试标样本完成 Embedding、保守聚类和分层 NLI 轻量回放。已冻结六个代表日期的37,137条历史事实，但 Argilla 尚未安装、人工标注未开始，分类质量、摘要、排名和整窗性能仍未准入。**

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
| Argilla URL/credential | `127.0.0.1:6900`；无仓库默认密钥 | 本机私密环境 | M1 标注导入导出 | 仅 loopback；不得写仓库 |

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

## 5. 当前验证

- M1、依赖矩阵和 legacy 护栏：45项通过。
- 现有新闻 DAO、页面去重、Wealth 新闻 API/Reader 回归：69项通过，只有既有 Starlette/httpx 弃用警告。
- Ruff、`compileall`、`git diff --check`：通过。
- 全仓测试：4,573项通过、10项跳过；当前沙箱禁止测试夹具绑定本机端口，导致345项本地 PostgreSQL类错误；另有33项非 M1 失败。`tests/news_intelligence/**` 无失败或错误，不能把该全仓结果表述为全绿。
- Prod 只读冻结实验：`m1-pilot-20260918-23-67185a66`，绑定 commit `67185a66`；`news=27,027`、`major_news=10,018`、`cctv_news=92`，共37,137条；来源内精确重复3,252条；试标导入包140条。完整制品为211 MiB，`SHA256SUMS` 复核通过，数据库事务为 `REPEATABLE READ, READ ONLY`。
- 首次模型回放 `m1-lightweight-pilot-25c08fb4` 暴露了 zero-shot 分数归一化错误：135个事件全部 `UNRESOLVED`。该制品保留为失败证据，不纳入质量评估。
- 修复后实验 `m1-lightweight-pilot-ec7b1cdf` 绑定 commit `ec7b1cdf`，`SHA256SUMS` 通过；140条候选形成135个事件，聚类规模为131个单条、3个两条、1个三条。临时阈值0.5下主题 `CLASSIFIED=95/UNRESOLVED=40`，事件类型 `CLASSIFIED=62/UNRESOLVED=21/NOT_APPLICABLE=52`；这些只证明推理语义已恢复，没有 gold label 前不构成准确率或阈值结论。
- 修复后140条轻量回放 wall-clock `511.34s`（约8.52分钟），主进程峰值 RSS `1,097,568 KiB`，模型子进程峰值 RSS `1,852,068 KiB`；结束后无模型进程、锁文件或监听端口残留。这是试标子集性能，不是最大整窗 `<60分钟` 准入证据。

## 6. 后续门禁

1. 安装 Docker Desktop 必须单独获得管理员授权；随后才能启动仅绑定 `127.0.0.1:6900` 的本机 Argilla。
2. 完成20条教学和120条盲标后停止，由用户评审 taxonomy；未确认前不生成800条正式集。
3. 人工 gold label 导出后才能计算候选召回、Macro-F1 与 PR 曲线，并据此调整当前临时0.5阈值。
4. 在 taxonomy 人工试标后完成 Qwen 摘要、事实核验和资源采样闭环。
5. 业务质量与最大窗口60分钟性能门禁未通过前不得进入M2。
