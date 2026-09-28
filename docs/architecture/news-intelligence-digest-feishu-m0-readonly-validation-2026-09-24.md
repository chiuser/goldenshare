# 新闻智能简报 M0 测量与实机验证报告（2026-09-24—2026-09-28）

状态：**M0-1/M0-2/M0-3 已完成；冻结制品已在 Prod HDD 隔离安装并完成 CPU 单模型基准，`cctv_news` 手动补数已通过当前数据完整性复核；业务质量和整窗 60 分钟门禁仍须 M1 回放验证，尚未开发、迁移、部署服务或发送飞书消息。**

依据：[新闻智能简报 LLD v1](/Users/congming/github/goldenshare/docs/architecture/news-intelligence-digest-feishu-low-level-design-v1.md) §10.1。数据观测时间为 2026-09-24 01:03–01:12（Asia/Shanghai）；用户批准 M0-3 后，于 2026-09-25 执行 HDD 隔离安装与实机基准，并于 2026-09-28 完成恢复复核。本阶段没有写数据库、修改项目 `.venv`、新增系统包、部署服务、开放公网端口或发送飞书消息。

---

## 1. 范围与口径

### 1.1 白名单

- Raw：`raw_tushare.news`、`raw_tushare.major_news`、`raw_tushare.cctv_news`；
- Serving：`core_serving_light` 同名三个 view，仅核验 relation 类型和字段合同；
- 系统目录：列、索引、relation 估算、大小和 tablespace；
- 服务器：CPU、内存、磁盘、项目虚拟环境中的模型相关包和 Hugging Face 缓存目录。

没有读取 `news.score` 或 `raw_payload`。正文只在 2026-09-17 22:00 至 2026-09-23 22:00 的有界样本中用于字符长度和规范化标题分组。

### 1.2 两种窗口统计

1. **抓取触达上界**：按当前 `fetched_at` 落入五个推送窗口统计。它包括首次插入和后续 upsert 刷新，是模型入口压力的保守上界。
2. **Raw `id` 水位模拟**：按窗口内可观察到的最大 `id` 模拟净新增。由于 Raw 没有 `created_at/first_seen_at`，且 upsert 会覆盖 `fetched_at`，旧数据不能精确重建当时的 cursor 快照；首个窗口没有可靠的历史起始水位，后续结果也只能作为下界代理。

因此，本文不会把历史 `fetched_at` 统计冒充正式净新增量。正式运行必须保存每个 Run 的 `last_raw_id/frozen_max_raw_id/discovered_count`，才能形成可复核事实。

---

## 2. 当前表与存储事实

| Raw 表 | 估算行数 | 总 relation 大小 | tablespace | 业务时间范围 |
|---|---:|---:|---|---|
| `news` | 8,791,894 | 7,318 MB | `gs_raw_cold_hdd` | 2022-01-01 00:00:47 至 2026-09-24 00:57:23 |
| `major_news` | 443,523 | 2,834 MB | `pg_default` | 2026-01-01 00:00:00 至 2026-09-24 00:46:08 |
| `cctv_news` | 34,126 | 60 MB | `pg_default` | 2020-01-01 至 2026-08-19 |

补充事实：

- 三张 Raw 表都有自增 `id` 主键、唯一 `row_key_hash` 和业务时间索引；不存在 `created_at` 或不可变首见时间。
- `fetched_at` 是 upsert 可更新字段，不等于首见时间，也不能直接当作真实迟到时间。
- `core_serving_light` 三个 relation 均为 view，不独立占表空间。
- HDD tablespace 实际路径为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`。
- 首次 M0 观测时，`cctv_news` 最新业务日期为 2026-08-19，较观测日已中断约 36 天；2026-09-18 至 2026-09-23 六天均为 0 行。该结论保留为当时的来源状态，不代表下文手动补数后的当前状态。

`cctv_news` 最近六个有数据日期为 2026-08-14 至 2026-08-19，每日 10–15 条，正文 P50 为 351–533 字，单篇最大 2,666 字。这只能用于长度校准，不能证明当前来源完整。

### 2.1 手动补数后的只读复核（2026-09-24 18:32）

用户完成手动更新后再次只读核验：

- Raw 当前精确总数为 36,581 行，`max(date)=2026-09-23`、`max(id)=36641`，最新 `fetched_at=2026-09-24 18:30:05+08`；在 2026-09-24 18:32、当日新闻联播尚未播出时，最新内容日期到 2026-09-23 符合预期。
- 2026-08-20 至 2026-09-23 连续 35 个内容日期均有数据，共 491 行；每日 10–18 行。连同被本次 upsert 刷新的 2026-08-19，共核验 505 行。
- 每日空标题、空正文、重复 `row_key_hash` 均为 0。
- `core_serving_light.cctv_news` 是 Raw 的字段投影视图；36 个日期逐日行数差均为 0，五个业务字段双向 `EXCEPT ALL` 均为 0 行，Serving 的 505 行 `source` 均为 `tushare`。

因此，**当前数据内容完整性门禁已恢复**。但这次是人工补数，尚未证明自动调度、失败告警和持续 freshness 已恢复；该事项由用户另行处理，不计入新闻智能 M0 剩余任务，但正式投递前仍须完成自动运行读回验收。

---

## 3. 30 个代表窗口

下表是按 `fetched_at` 统计的抓取触达上界；`cctv_news` 在全部窗口均为 0。

| 日期 | 时点 | news | major_news | 合计 |
|---|---:|---:|---:|---:|
| 2026-09-18 | 08:00 | 6,046 | 1,781 | 7,827 |
| 2026-09-18 | 12:00 | 89 | 11 | 100 |
| 2026-09-18 | 16:00 | 44 | 21 | 65 |
| 2026-09-18 | 20:00 | 82 | 62 | 144 |
| 2026-09-18 | 22:00 | 27 | 12 | 39 |
| 2026-09-19 | 08:00 | 5,715 | 1,925 | 7,640 |
| 2026-09-19 | 12:00 | 56 | 5 | 61 |
| 2026-09-19 | 16:00 | 45 | 6 | 51 |
| 2026-09-19 | 20:00 | 37 | 1 | 38 |
| 2026-09-19 | 22:00 | 20 | 4 | 24 |
| 2026-09-20 | 08:00 | 1,768 | 721 | 2,489 |
| 2026-09-20 | 12:00 | 18 | 1 | 19 |
| 2026-09-20 | 16:00 | 15 | 21 | 36 |
| 2026-09-20 | 20:00 | 29 | 64 | 93 |
| 2026-09-20 | 22:00 | 37 | 7 | 44 |
| 2026-09-21 | 08:00 | 1,792 | 1,370 | 3,162 |
| 2026-09-21 | 12:00 | 31 | 3 | 34 |
| 2026-09-21 | 16:00 | 49 | 11 | 60 |
| 2026-09-21 | 20:00 | 66 | 75 | 141 |
| 2026-09-21 | 22:00 | 46 | 15 | 61 |
| 2026-09-22 | 08:00 | 5,435 | 1,729 | 7,164 |
| 2026-09-22 | 12:00 | 80 | 23 | 103 |
| 2026-09-22 | 16:00 | 50 | 24 | 74 |
| 2026-09-22 | 20:00 | 74 | 54 | 128 |
| 2026-09-22 | 22:00 | 28 | 10 | 38 |
| 2026-09-23 | 08:00 | 5,678 | 1,768 | 7,446 |
| 2026-09-23 | 12:00 | 43 | 13 | 56 |
| 2026-09-23 | 16:00 | 70 | 40 | 110 |
| 2026-09-23 | 20:00 | 44 | 83 | 127 |
| 2026-09-23 | 22:00 | 52 | 29 | 81 |

六天触达总量为 `news=27,566`、`major_news=9,889`，即 37,455 行。最高两个极端窗口为：

1. 2026-09-18 08:00：7,827 行；
2. 2026-09-19 08:00：7,640 行。

除去无法建立可靠起始水位的首日，`id` 高水位模拟的两个最高窗口是 2026-09-23 08:00 的 906 行和 2026-09-22 08:00 的 876 行。真实正式负载位于“约 900 个净新增代理”与“约 7,800 个抓取触达上界”之间；只有上线 shadow cursor 后才能收窄。

---

## 4. 文本、空值、重复与事件代理

### 4.1 摘要阈值

| 来源 | 样本行数 | ≥400 字 | ≥800 字 | ≥1,500 字 | 空标题 | 空正文 |
|---|---:|---:|---:|---:|---:|---:|
| `news` | 27,566 | 627 | 48 | 2 | 12,931 | 0 |
| `major_news` | 9,889 | 9,860 | 9,764 | 9,542 | 0 | 0 |

结论：默认 **800 个字符** 是合理的一期摘要门槛。它只命中 `news` 的 0.17%，却覆盖 `major_news` 的 98.74%；短快讯不摘要，长通讯进入摘要资格。这个门槛是版本化 policy，可在 M1 样本验收后调整，但不得让 8,000 条窗口全部进入生成模型。

窗口级正文分布：

- `news`：P50 约 73–187 字，P95 约 204–719 字，样本最大 2,037 字；
- `major_news`：大多数窗口 P50 约 5,000–7,000 字，P95 常在 16,000 字附近，样本最大 182,198 字；
- `news` 空标题率为 46.91%，因此标题缺失时必须由正文抽取展示标题；两个来源正文均无空值。

### 4.2 重复与事件估算

- `row_key_hash` 有唯一索引，物理身份重复为 0；这不等于跨来源、同事件重复为 0。
- 对标题为空时回退正文前 200 字，做小写化并移除非字母数字字符的简化规范化标题分组：`news` 约 22,290 组 / 27,566 行，`major_news` 约 9,491 组 / 9,889 行。
- 两来源相加后，精确标题代理约减少 15.1% 候选；它会拆开改写标题，也可能合并同名不同事件，不能替代现有 `deduplicate_news_events` 或 M1 人工验证。
- 按 `id` 水位代理、排除首日后，五天为 4,147 行、3,636 个跨来源规范化标题组，约减少 12.3%。最高可靠代理窗口 2026-09-23 08:00 为 906 行、790 组。

### 4.3 “迟到”只能记录代理值

窗口内 `fetched_at - business_time` 的 P50/P95 大体落在 0.27–17.51 小时 / 0.27–22.99 小时，但 `fetched_at` 会被重复 upsert 改写。这些数值只能称为“业务发布时间到最近抓取时间差”，不能作为首见延迟 SLA。

正式表必须保存不可变 `discovered_at`，并同时保存业务发布时间、Raw `id` 和 Run 冻结时点；迟到统计从正式 shadow Run 开始建立。

---

## 5. HDD 容量

最近 10,000 行 `pg_column_size` 均值为：`news=519 B`、`major_news=5,639 B`、`cctv_news=1,517 B`。按当前 total relation/估算行数折算，包含 TOAST 与索引后的物理量级约为 `news=873 B/行`、`major_news=6.7 KB/行`、`cctv_news=1.8 KB/行`。

以六天抓取触达量作为保守上界，Raw 等价增长约 5.1 GiB/年。新闻智能库不复制原文，只存身份、特征、embedding、摘要、评分、版本和投递记录；M0 仍建议按 **10 GiB/年** 为一期做容量预算，覆盖索引、JSONB、事件版本和估算误差。

Prod HDD `/data/disk` 为 394 GiB，总可用 264 GiB；按 10 GiB/年预算具备多年余量。所有新 relation 仍必须显式放入 `gs_raw_cold_hdd`，禁止因为容量足够而落回根盘 SSD。

---

## 6. Prod 资源与模型现状

| 项目 | 只读观测 |
|---|---|
| CPU | 8 vCPU，Intel Xeon Platinum 8255C，AVX2/AVX-512/VNNI |
| 内存 | 15 GiB，总可用约 9.5 GiB；已有约 5.7 GiB 使用 |
| Swap | 9.9 GiB，已有约 1.1 GiB 使用 |
| 根盘 | 266 GiB，已用 222 GiB，余 34 GiB，使用率 88% |
| HDD | 394 GiB，已用 110 GiB，余 264 GiB，使用率 30% |
| Python | 项目虚拟环境 Python 3.13.12 |
| 模型依赖 | 目标清单中只匹配到 `numpy==2.4.4`；未发现 Torch、Transformers、Sentence Transformers、ONNX Runtime、llama.cpp、scikit-learn、jieba、FlagEmbedding 或 vLLM |
| 模型缓存 | 未发现已存在的 Hugging Face 模型缓存目录 |

结论：Prod 是 CPU-only、小内存余量环境，不能把 embedding、mDeBERTa 和生成模型常驻并发运行。M0-3 已按 §6.2 冻结清单完成隔离安装和单模型串行 benchmark；结果见 §6.3。

### 6.1 模型候选制品冻结（2026-09-24）

本节记录 M0-2 当时冻结的安装申请和 CPU benchmark 输入；后续下载、运行验证与基准结果见 §6.3。完成 M0-3 仍不代表业务质量已通过或已获准部署生产 Worker。所有 revision 均使用完整 commit SHA，禁止运行时解析浮动 `main`。

| 职责 | 冻结候选 | revision / 文件 | 权重大小与校验 | 许可证 | 当前结论 |
|---|---|---|---|---|---|
| Embedding / 聚类 | [`Qwen/Qwen3-Embedding-0.6B`](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` / `model.safetensors` | 1,191,586,416 bytes；SHA-256 `0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd` | Apache-2.0 | **冻结为主候选**；BF16、0.6B、1024 维，先测 CPU RSS、batch 与窗口吞吐 |
| 多标签分类 / NLI | [`MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli) | `8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c` / `onnx/model_quantized.onnx` | 338,679,133 bytes；SHA-256 `27c39e884c14b03cf46cfc5485971b6db70ff330220d93dfe729c63fde43af0e` | MIT | **冻结为 CPU 主候选**；M1 必须验证中文多标签和摘要句支持度，不能因模型名直接判定合格 |
| 有界生成 / 摘要 | [`Qwen/Qwen3-4B-GGUF`](https://huggingface.co/Qwen/Qwen3-4B-GGUF) | `bc640142c66e1fdd12af0bd68f40445458f3869b` / `Qwen3-4B-Q4_K_M.gguf` | 2,497,280,256 bytes；SHA-256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` | Apache-2.0 | **冻结为官方 CPU benchmark 候选**；使用 `llama.cpp` 路径，M1 通过摘要事实性、JSON 合法率和排名增益后才能成为一期模型 |

模型卡和 Hugging Face API 的当前证据同时说明：

1. Embedding 官方模型支持中文、多语言、聚类/分类任务；官方要求 `transformers>=4.51.0`，并提供 Sentence Transformers/Transformers 用法。实际最大输入、instruction、截断和 batch 仍由 M1 冻结。
2. mDeBERTa 模型明确支持多语言 NLI/零样本分类，原模型仓库同时提供 safetensors 与量化 ONNX；为适配 CPU 和内存约束，首轮只申请量化 ONNX 制品，不同时下载 557 MB 的 safetensors 基线。
3. 原方案写的 [`Qwen/Qwen3-4B-Instruct-2507`](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) 官方 revision 为 `cdbee75f17c01a7cc42f958dc650907174af0554`，BF16 三个分片合计 8,044,982,000 bytes（约 8.0 GB），官方仓库没有 4-bit GGUF。它继续作为语义质量参考，**不列入本轮 Prod 下载清单**；未经单独来源、转换过程、校验和与质量验证的社区 GGUF 不准入。
4. `Qwen3-4B-GGUF` 来源于原始 `Qwen3-4B`，不是 `Instruct-2507` 的同一权重。它只是硬件可行性更高的官方候选，不构成自动换模；若 M1 未通过，就停止生成模型准入并重新提出制品方案。

三个冻结权重主文件合计 4,027,545,805 bytes（约 4.03 GB，十进制）。这不是最终下载总量；tokenizer、配置文件和经审核的推理运行时必须在下一步依赖清单中逐项计算。

### 6.2 M0-2 推理依赖、安装位置与完整下载清单（2026-09-24）

#### 6.2.1 目标平台与隔离边界

2026-09-24 只读复核确认 Prod 为 Ubuntu 24.04、x86_64、glibc 2.39、Python 3.13.12；现有项目虚拟环境有 `pip 26.1` 和可用的标准库 `venv`，没有 `uv`、CMake 或模型运行时。`/data/disk` 是可写挂载的 ext4 HDD，但根目录为 `root:root 0755`，当前只存在 PostgreSQL 目录。

安装合同如下：

| 项目 | 冻结值 | 原因与门禁 |
|---|---|---|
| 专用根目录 | `/data/disk/goldenshare/news-intelligence` | 模型、wheelhouse、venv、llama.cpp、cache、tmp 全部落 HDD；不得写入根盘模型缓存 |
| 目录属主/权限 | `goldenshare:goldenshare` / `0750` | 须由管理员一次性创建；之后只由 `goldenshare` 用户维护，不开放其他用户写入 |
| Python 解释器 | 复用现有 Python 3.13.12，仅用于创建专用 venv | 不下载新解释器，不修改 `/opt/goldenshare/goldenshare/.venv` |
| Python venv | `runtime/python-3.13-m0-v1/venv` | 44 个 wheel 全量锁定；只允许 `--require-hashes` 从本地 wheelhouse 安装 |
| Wheelhouse | `artifacts/wheelhouse-m0-v1` | 先完整下载并校验，再离线安装；禁止边运行边解析 PyPI |
| llama.cpp | `runtime/llama.cpp/b11146` | 使用官方 Ubuntu x64 CPU 预编译制品，不在 Prod 现场编译 |
| 模型目录 | `models/<model-id>/<revision>/` | revision 是目录身份；下载后生成本地 SHA-256 manifest，再原子提升 |
| 临时目录/缓存 | `staging/`、`cache/huggingface/`、`tmp/` | benchmark 时显式设置 `HF_HOME`、`HF_HUB_CACHE`、`TRANSFORMERS_CACHE`、`TMPDIR` 到 HDD；运行阶段启用 HF/Transformers offline |
| SSD 写入 | 只允许已有仓库代码和少量系统服务定义 | 权重、wheel、venv、模型缓存、运行临时文件不得进入 `/opt`、用户 home 或 `/tmp` |

`/data/disk` 根目录创建子目录并授权在 M0-2 时只是待审批系统变更，M0-3 获批后已按本表执行。M0-3 没有新增环境变量或 Settings；后续若把路径加入服务配置，必须先完成根规则要求的配置项审计。

#### 6.2.2 冻结的直接运行时

| 运行时 | 制品 | bytes | SHA-256 | 来源/用途 |
|---|---|---:|---|---|
| PyTorch CPU | `torch-2.14.0+cpu-cp313-cp313-manylinux_2_28_x86_64.whl` | 196,253,940 | `160e1bc46aeded3111d2801f8ae10dc9a1b946843a7e126b4dbf5e19c5706e95` | PyTorch 官方 CPU index；Embedding |
| Transformers | `transformers-5.17.0-py3-none-any.whl` | 12,295,140 | `78ec1ce21579b38dfb83950a0658cd119f87212a2fcfdff478096ce9d6c03801` | PyPI；模型与 tokenizer 合同 |
| Sentence Transformers | `sentence_transformers-6.1.0-py3-none-any.whl` | 740,560 | `eb8122f4d180f552eda26dc3d77e84e8c11dc2b1d456a406b9f24abb70ceeadd` | PyPI；Embedding pooling/normalize |
| ONNX Runtime CPU | `onnxruntime-1.30.0-cp313-cp313-manylinux_2_28_x86_64.whl` | 23,585,560 | `86f940afc801ea9681a4da8af84fbe95e1d9ea7d80903952cc1bfad54faad38f` | PyPI；量化 mDeBERTa |
| llama.cpp | `llama-b11146-bin-ubuntu-x64.tar.gz`，commit `7fe450e19305b828c199d602c23a8337aaa1f03b` | 16,998,357 | `c150306eb16b5ab696f76a8bdf810c35fd98a24e82158742e6fa28f420ff8410` | 官方 GitHub release；Q4_K_M 推理 |

Python 依赖使用 `uv 0.11.14` 只读解析元数据，目标为 CPython 3.13 / `x86_64-manylinux_2_28` / CPU-only / binary-only，并设置统一发布截止时间 `2026-09-20T00:00:00Z`，避免 9 月 20 日之后新发布的传递依赖随时间漂移。`uv` 只是 M0-2 本地解析工具，不进入 Prod 安装清单。

#### 6.2.3 Python wheel 完整锁（44 个）

下表是目标平台唯一选择的 wheel；`bytes` 合计 **318,951,565**。安装时须把相同 filename 与 SHA-256 写成 `--require-hashes` 清单，任意缺失、源码包回退或哈希变化立即停止。

| 包 | 文件 | bytes | SHA-256 |
|---|---|---:|---|
| `annotated-doc==0.0.5` | `annotated_doc-0.0.5-py3-none-any.whl` | 5,302 | `117bac03a25ede5df5440e855b32d556049ca169ead221505badf432fed4b101` |
| `anyio==4.15.1` | `anyio-4.15.1-py3-none-any.whl` | 132,079 | `6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101` |
| `certifi==2026.7.22` | `certifi-2026.7.22-py3-none-any.whl` | 136,983 | `62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775` |
| `click==8.5.0` | `click-8.5.0-py3-none-any.whl` | 125,251 | `255bc9599cf7748b4b1a446ccc735421bd08a2ae529a8b88597d3de5664ee360` |
| `cloudpickle==3.1.2` | `cloudpickle-3.1.2-py3-none-any.whl` | 22,228 | `9acb47f6afd73f60dc1df93bb801b472f05ff42fa6c84167d25cb206be1fbf4a` |
| `filelock==4.0.1` | `filelock-4.0.1-py3-none-any.whl` | 106,219 | `481a321a27bef441e23c53371c6abc8d7d16e26b97090074ba44f7538a3fd55a` |
| `flatbuffers==25.12.19` | `flatbuffers-25.12.19-py2.py3-none-any.whl` | 26,661 | `7634f50c427838bb021c2d66a3d1168e9d199b0607e6329399f04846d42e20b4` |
| `fsspec==2026.9.0` | `fsspec-2026.9.0-py3-none-any.whl` | 221,738 | `8dd6e646e99ea382bd85f97a45e6b526a442d79423a7dc673f1e2756d05fcb5f` |
| `h11==0.16.0` | `h11-0.16.0-py3-none-any.whl` | 37,515 | `63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86` |
| `hf-xet==1.6.0` | `hf_xet-1.6.0-cp38-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | 4,464,663 | `d62671bb130879cef0ee4c9ebe47a14af6c66ec53e6d84dc15936e5ffdfac82f` |
| `httpcore==1.0.9` | `httpcore-1.0.9-py3-none-any.whl` | 78,784 | `2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55` |
| `httpx==0.28.1` | `httpx-0.28.1-py3-none-any.whl` | 73,517 | `d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad` |
| `huggingface-hub==1.32.0` | `huggingface_hub-1.32.0-py3-none-any.whl` | 842,906 | `b0c7c80561969d9cdacdd55fce67ba9584cca0b9d4ea80957a3a5c1445fac5c8` |
| `idna==3.20` | `idna-3.20-py3-none-any.whl` | 69,583 | `ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c` |
| `jinja2==3.1.6` | `jinja2-3.1.6-py3-none-any.whl` | 134,899 | `85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67` |
| `joblib==1.6.0` | `joblib-1.6.0-py3-none-any.whl` | 306,115 | `3dbbf9f6e4b592a2357b854608e980fe6390d131d7a82f011a377ef2ebef7aba` |
| `markdown-it-py==4.2.0` | `markdown_it_py-4.2.0-py3-none-any.whl` | 91,687 | `9f7ebbcd14fe59494226453aed97c1070d83f8d24b6fc3a3bcf9a38092641c4a` |
| `markupsafe==3.0.3` | `markupsafe-3.0.3-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` | 22,980 | `ccfcd093f13f0f0b7fdd0f198b90053bf7b2f02a3927a30e63f3ccc9df56b676` |
| `mdurl==0.1.2` | `mdurl-0.1.2-py3-none-any.whl` | 9,979 | `84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8` |
| `mpmath==1.3.0` | `mpmath-1.3.0-py3-none-any.whl` | 536,198 | `a0b2b9fe80bbcd81a6647ff13108738cfb482d481d826cc0e02f5b35e5c88d2c` |
| `narwhals==2.26.0` | `narwhals-2.26.0-py3-none-any.whl` | 474,034 | `29326d74f107c347fd1009bd58e38d9f7c7c5b51e6de97bc93dbc325d9038b54` |
| `networkx==3.6.1` | `networkx-3.6.1-py3-none-any.whl` | 2,068,504 | `d47fbf302e7d9cbbb9e2555a0d267983d2aa476bac30e90dfbe5669bd57f3762` |
| `numpy==2.5.3` | `numpy-2.5.3-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | 16,708,577 | `a5fa86b80fd24bcd1aff83ad23be44ea323de3f787be8f8b15d4a65621e25321` |
| `onnxruntime==1.30.0` | `onnxruntime-1.30.0-cp313-cp313-manylinux_2_28_x86_64.whl` | 23,585,560 | `86f940afc801ea9681a4da8af84fbe95e1d9ea7d80903952cc1bfad54faad38f` |
| `packaging==26.3` | `packaging-26.3-py3-none-any.whl` | 129,956 | `d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c` |
| `protobuf==7.36.2` | `protobuf-7.36.2-cp310-abi3-manylinux2014_x86_64.whl` | 343,223 | `89f23aa53c24553a2416fd4fd1ec06f74fa42b14b546d8883128813f775bbfd2` |
| `pygments==2.21.0` | `pygments-2.21.0-py3-none-any.whl` | 1,250,147 | `2363c69b61c4a97c838da3b130dcd6468f4848992b21a82f2a63ec34377137d9` |
| `pyyaml==6.0.3` | `pyyaml-6.0.3-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` | 801,626 | `0f29edc409a6392443abf94b9cf89ce99889a1dd5376d94316ae5145dfedd5d6` |
| `regex==2026.9.10` | `regex-2026.9.10-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl` | 804,578 | `bafa41b0dd63669e5c0f8adf3d24819efeb73c847f492eb011212eb352e69041` |
| `rich==15.0.0` | `rich-15.0.0-py3-none-any.whl` | 310,654 | `33bd4ef74232fb73fe9279a257718407f169c09b78a87ad3d296f548e27de0bb` |
| `safetensors==0.8.0` | `safetensors-0.8.0-cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | 516,040 | `fd6f3f93c9a0a7cc2788ee63fb763353d4bd2e89b0751bc78fcf7dda00bea774` |
| `scikit-learn==1.9.1` | `scikit_learn-1.9.1-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | 9,121,732 | `55e79d6e9b0923f1a978179822bd43d7f5543f45e970a00fe861f43486380aba` |
| `scipy==1.18.1` | `scipy-1.18.1-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` | 35,312,578 | `fdaf5ea890a6183d0565f51a61799d67081bd5b1cf03c5f4b3fd3732108625c9` |
| `sentence-transformers==6.1.0` | `sentence_transformers-6.1.0-py3-none-any.whl` | 740,560 | `eb8122f4d180f552eda26dc3d77e84e8c11dc2b1d456a406b9f24abb70ceeadd` |
| `setuptools==84.0.0` | `setuptools-84.0.0-py3-none-any.whl` | 818,216 | `51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670` |
| `shellingham==1.5.4` | `shellingham-1.5.4-py2.py3-none-any.whl` | 9,755 | `7ecfff8f2fd72616f7481040475a65b2bf8af90a56c89140852d1120324e8686` |
| `sympy==1.14.0` | `sympy-1.14.0-py3-none-any.whl` | 6,299,353 | `e091cc3e99d2141a0ba2847328f5479b05d94a6635cb96148ccb3f34671bd8f5` |
| `threadpoolctl==3.7.0` | `threadpoolctl-3.7.0-py3-none-any.whl` | 26,362 | `cd8b60b5641b45c67bbf73c64c843235fc2d8a480c87389f52f5dbee893b86be` |
| `tokenizers==0.23.2` | `tokenizers-0.23.2-cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | 3,386,843 | `41c2f84d172449b4dadb9cdc508e3e364076613c35b16e76ecfe47a60d1e3305` |
| `torch==2.14.0+cpu` | `torch-2.14.0+cpu-cp313-cp313-manylinux_2_28_x86_64.whl` | 196,253,940 | `160e1bc46aeded3111d2801f8ae10dc9a1b946843a7e126b4dbf5e19c5706e95` |
| `tqdm==4.70.1` | `tqdm-4.70.1-py3-none-any.whl` | 80,199 | `c293e525e6fef9c20e8728fd4612df02a0aa31bb5fe91ecd93e123b1b7bffa73` |
| `transformers==5.17.0` | `transformers-5.17.0-py3-none-any.whl` | 12,295,140 | `78ec1ce21579b38dfb83950a0658cd119f87212a2fcfdff478096ce9d6c03801` |
| `typer==0.27.2` | `typer-0.27.2-py3-none-any.whl` | 123,130 | `b3a5fc4342d5fc8fda8fc3010b1cf117e9249aab7fae800c2eff62fd3842d97d` |
| `typing-extensions==4.16.0` | `typing_extensions-4.16.0-py3-none-any.whl` | 45,571 | `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` |

#### 6.2.4 模型文件与总下载量

| 组 | 下载内容 | bytes |
|---|---|---:|
| Embedding | §6.1 权重，加 pooling/config/tokenizer/merges/vocab 等 9 个附属文件 | 1,207,470,234 |
| mDeBERTa | §6.1 量化 ONNX，加 config、SentencePiece、tokenizer 与 special token 文件 | 359,318,185 |
| Qwen GGUF | §6.1 `Qwen3-4B-Q4_K_M.gguf` | 2,497,280,256 |
| Python wheelhouse | §6.2.3 的 44 个 wheel | 318,951,565 |
| llama.cpp | `llama-b11146-bin-ubuntu-x64.tar.gz` | 16,998,357 |
| **合计** | 不包含已有 Python 解释器，不包含任何 CUDA/ROCm 制品 | **4,400,018,597 bytes（4.40 GB / 约 4.10 GiB）** |

HDD 安装容量门禁设为 **至少 12 GiB 可用**，覆盖压缩包保留、venv 解包、同文件系统 staging、运行缓存和测量误差；这不是模型业务数据的 10 GiB/年容量预算。M0-3 执行前复核余量约 264 GiB，满足门禁；2026-09-28 恢复复核余 257 GiB。

#### 6.2.5 获批安装的强制顺序（M0-3 已按此执行）

1. 只创建并授权上述 HDD 根目录；确认真实路径仍位于 `/data/disk`，剩余空间 `>=12 GiB`。
2. 下载 44 个 wheel、llama.cpp tarball 和三个 revision 的白名单模型文件到 HDD `staging/`；禁止下载整个仓库的非白名单权重，禁止 CUDA/ROCm 包。
3. 对所有已声明 SHA-256 的制品逐个校验；对 revision 内小型 tokenizer/config 文件生成本地 SHA-256 manifest。任一不一致停止，不安装。
4. 从现有 Python 3.13.12 创建专用 venv，以 `--no-index --find-links ... --require-hashes` 离线安装；不得修改项目 `.venv`。
5. 解包 llama.cpp 后先做 `llama-server --version`、动态库检查和本地回环启动；不开放公网端口。
6. 执行四层 smoke test：imports/版本、Embedding 单条、mDeBERTa 单条 NLI、Qwen GGUF 单条受限 JSON；任何失败先回滚专用目录，不安装 apt 包或切换浮动版本救场。
7. smoke test 通过后才进入 M0-3 的 RSS、CPU、P50/P95、batch、最大输入和窗口余量 benchmark。

M0-2 不包含 Argilla、Web/Ops 现有依赖、CUDA/ROCm、vLLM、FlashAttention、TEI、Docker 镜像、模型训练包、Reranker 或 `Qwen3-4B-Instruct-2507` BF16。后续如需任何一项，必须重新给出制品、大小、哈希、路径与理由。

### 6.3 M0-3 Prod HDD 安装与 CPU 实机基准（2026-09-25，2026-09-28 复核）

#### 6.3.1 安装与制品验收

- 专用根已创建为 `/data/disk/goldenshare/news-intelligence`，属主/权限为 `goldenshare:goldenshare 0750`；模型、wheelhouse、独立 venv、llama.cpp、cache、tmp 和 benchmark 证据均在 `/data/disk` HDD。项目 `.venv` 未改变。
- 44 个 CPU wheel、18 个模型文件和 llama.cpp b11146 均按冻结文件名/大小安装；三个主权重与 llama.cpp tarball 的 SHA-256 再验结果与 §6.1/§6.2 一致。专用 venv 离线安装后 `pip check` 返回 `No broken requirements found`。
- Python 运行时为 3.13.12；实测导入 `torch 2.14.0+cpu`、`transformers 5.17.0`、`sentence-transformers 6.1.0`、`onnxruntime 1.30.0`、`numpy 2.5.3`、`scikit-learn 1.9.1`，`torch.cuda.is_available()` 为 false。
- Prod 到 `huggingface.co` 的解析结果不可用，而官方 `cdn.hf.co` 可达；因此下载由本地通过官方 HTTPS 流式写入 Prod HDD，再在 Prod 做大小和 SHA-256 验证。它是安装期网络事实，不允许实现运行时联网或解析浮动 revision。
- 最终目录约 5.6 GiB；2026-09-28 复核 HDD 余 257 GiB。失败 smoke 产生的两份纯重复交互日志已清空，成功输出、4 KiB 摘要和全部 benchmark JSON 保留。

#### 6.3.2 单模型基准

统一条件：CPU-only、4 线程、模型串行运行；延迟是单模型调用耗时，不含数据库读取、清洗、聚类算法、持久化、进程装载/卸载和最终排序。

| 模型/输入 | batch / 次数 | P50 | P95 | 吞吐 | 峰值 RSS | 结论 |
|---|---:|---:|---:|---:|---:|---|
| Embedding，128 tokens | 1 / 10 | 1.518 s | 2.416 s | 0.659 条/s | 约 1.37 GiB（该 case） | batch 1 最优；batch 4/8/16 的单条吞吐继续下降 |
| Embedding，512 tokens | 1 / 5 | 8.379 s | 8.963 s | 0.119 条/s | 全程最高约 1.78 GiB | M1 初始输入硬上限取 512 tokens；不得把全文直接送入 |
| Embedding，1,024 tokens | 1 / 3 | 15.612 s | 15.638 s | 0.064 条/s | 同上 | 只证明边界可运行，不作为一期默认 |
| mDeBERTa，124 tokens | 16 / 8 | 1.161 s/批 | 1.195 s/批 | 13.785 对/s | 约 1.33 GiB（该 case） | M1 初始 batch 16 |
| mDeBERTa，490 tokens | 1 / 8 | 0.549 s | 0.572 s | 1.823 对/s | 全程最高约 1.49 GiB | 模型硬上限 512 tokens |
| Qwen 4B，120 字/86 prompt tokens | 1 / 10 | 4.963 s | 5.434 s | prompt 26.51、生成 6.83 tokens/s | 全程最高约 4.35 GiB | `threads=4, parallel=1, ctx=2048` 可运行 |
| Qwen 4B，800 字/427 prompt tokens | 1 / 5 | 19.598 s | 19.696 s | prompt 25.14、生成 5.80 tokens/s | 同上 | 30 次按 P95 约 9.85 分钟 |
| Qwen 4B，1,400 字/728 prompt tokens | 1 / 3 | 31.264 s | 31.330 s | prompt 25.46、生成 5.09 tokens/s | 同上 | 30 次按 P95 约 15.67 分钟 |

Embedding 全组 wall-clock 为 9:14.52、峰值 RSS 1,864,468 KiB、0 swap；mDeBERTa 全组为 48.33 秒、峰值 RSS 1,559,824 KiB、0 swap。Qwen 由持久 loopback server 顺序承载请求，benchmark 记录峰值 RSS 4,556,420 KiB；只监听 `127.0.0.1`，结束后无残留进程或监听端口。

#### 6.3.3 正确解释与窗口门禁

1. smoke test 证明三条运行链可用，不证明中文分类、聚类、摘要事实性或排序质量。mDeBERTa 单例偏向 neutral；Qwen benchmark 的固定 grammar 允许空摘要字符串，说明 schema 合法也不等于业务有效，必须由 M1 人工样本和非空/证据校验决定准入。
2. llama.cpp b11146 的 JSON Schema 自动转 grammar 路径在本次 smoke 中失败；显式 GBNF 可产生合法 JSON。M1 只能使用版本化显式 grammar 加应用层 JSON/schema/非空/证据校验，不能依赖自动转换成功。
3. 一次 SSH 中断曾留下 Qwen 子进程；并发启动第二实例后组合常驻约 8.4 GiB，并出现约 18 MiB swap 增量。进程全部终止后资源恢复。这直接冻结了“单实例、单模型驻留、进程组级超时/取消清理、启动前 singleton 断言”的运行门禁。
4. 历史最高可靠代理窗口为 906 条、规范化标题代理为 790 组。按 790 个 128-token Embedding 的 P95 估算约 31.8 分钟；若对每组平铺执行 17 个一级主题和 22 个事件类型共 39 个 NLI 假设，按 batch 16 的 P50 仍约 37.2 分钟；再加 30 个 1,400 字 Qwen 调用约 15.7 分钟，单模型部分合计约 84.7 分钟，尚未计入其他阶段。
5. 因而 M0-3 **没有通过整窗 60 分钟门禁**，也不能从单模型结果宣称最短两小时间隔已有充足余量。M1 必须用真实旧日期回放证明：精确去重后的实际事件数、Embedding 代表文本长度、分层/候选化 NLI 假设数和 Qwen 实际入选数；禁止对 39 个标签做全量平铺，禁止把 7,827 条触达上界直接送入任何模型。
6. M1 初始运行上限冻结为：Embedding `batch=1, max_tokens=512`；mDeBERTa `batch=16, max_tokens=512`；Qwen `threads=4, parallel=1, ctx=2048`，`deep_analysis_limit=30`。这些是回放安全上限，不是生产准入结论；M1 只能调低，若要调高必须重新证明 60 分钟和不依赖 swap。

#### 6.3.4 进程入口决定

一期目标形态冻结为独立的 App-owned 模型 Worker，不与 Web/Ops Worker 同进程。Worker 按阶段启动并回收单一模型子进程：Embedding 与 ONNX adapter 不同时常驻，Qwen 通过仅绑定 `127.0.0.1` 的 llama-server 提供单并发调用；每次启动记录 PID/进程组、模型 revision 和预算，取消、超时、异常及 Worker 退出均清理完整进程组。当前只冻结设计，M0-3 没有创建 systemd unit、环境变量或常驻服务；实现前仍须完成配置项审计。

#### 6.3.5 恢复与现有服务复核

2026-09-28 复核时没有 `llama-cli/llama-server` 残留，端口 18183 未监听；内存 available 约 9.7 GiB，既有 swap 使用约 1.2 GiB；`goldenshare-web`、`goldenshare-ops-worker`、`goldenshare-ops-scheduler` 均为 active。M0-3 没有变更数据库、项目代码、项目环境、systemd 或业务配置。

---

## 7. 回写到实现的参数与门禁

| 项目 | M0 结论 |
|---|---|
| 推送窗口 | 保持 08/12/16/20/22；08:00 是绝对峰值窗口 |
| Raw discovery batch | 初始 500 行；一个 7,800 行上界窗口约 16 批，批批提交、可续跑 |
| 摘要资格 | 默认正文 `>=800` 字；仍须先通过事件选择和深分析预算，不是所有长文都摘要 |
| 模型入口 | 严禁直接把全触达候选交给生成模型；先精确去重、规则筛选和事件聚合 |
| 模型候选制品 | 三个首轮制品的 repo/revision/文件/SHA-256 已冻结；不得解析浮动 `main`，不得直接采用社区 GGUF |
| M0-2/M0-3 运行时 | 冻结清单已在 HDD 隔离安装并校验；项目 `.venv` 不变；三模型只能串行、单实例运行 |
| M1 模型安全上限 | Embedding `batch=1/max_tokens=512`；mDeBERTa `batch=16/max_tokens=512`；Qwen `threads=4/parallel=1/ctx=2048/deep_analysis_limit=30` |
| 整窗性能 | 单模型可运行，但 790 组保守组合估算约 84.7 分钟；60 分钟门禁未通过，须由 M1 真实回放收缩入口并重新验收 |
| 容量预算 | 新 HDD 业务关系按 10 GiB/年预留；不复制原文 |
| 历史回放 | 使用业务时间做分层取样，只用于校准；不得声称复原了历史 Raw 净新增窗口 |
| 迟到指标 | M0 不产出真实首见 SLA；从 shadow Run 的不可变 `discovered_at` 开始统计 |
| 来源完整性 | `cctv_news` 手动补数后的当前数据已通过；自动更新由用户另行处理，仍是正式投递前的外部依赖，不计入 M0 剩余任务 |

---

## 8. M0 结论与下一门禁

M0 的数据、容量、制品、隔离运行时和单模型 CPU 基准均已完成，足以进入 M1 离线 replay/标注；但 M0-3 明确证明整窗 60 分钟门禁尚未通过，不能据此进入正式持久化、常驻 Worker、Shadow 或投递开发。M1 的性能目标不是增加并发，而是通过确定性清洗、精确去重、短代表文本、分层分类和有界 `deep_analysis_limit=30` 缩小模型入口，并用真实冻结窗口重新测量端到端耗时。

`cctv_news` 自动更新、失败告警和持续 freshness 由用户另行处理；它仍是正式投递前的外部依赖，但不再作为本项目 M0 的未完成项。

M1 应先实现隔离离线 replay 并在本地部署 Argilla，使用业务时间分层抽取 100–150 条 taxonomy 试标样本；它不依赖历史净新增窗口精确可重建，也不写正式 Run/cursor/delivery。M1 必须同时产出分类质量、聚类质量、Qwen 非空/事实性和代表性窗口端到端性能报告；任一门禁失败都停在 M1。
