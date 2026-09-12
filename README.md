# goldenshare

财势乾坤行情与数据运营项目。仓库包含业务 Web/API、运营前端、数据基座及独立量化产品域；不是只有平台基础设施的早期骨架。

## 阅读入口

- [文档索引](/Users/congming/github/goldenshare/docs/README.md)：按主题查找当前规范与历史记录。
- [仓库规则](/Users/congming/github/goldenshare/AGENTS.md)：授权、开发及数据操作边界。
- [子系统架构基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)：Foundation / Ops / Biz / App 与 QTF 的职责、依赖和现存差距。
- [前端当前规范](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)：运营 frontend 的组件、交互与验证入口。

后端主要使用 Python、SQLAlchemy、Alembic、Pydantic、Typer；运营 frontend 使用 React、TypeScript、Vite、Mantine、TanStack Query/Router。版本与依赖以 [pyproject.toml](/Users/congming/github/goldenshare/pyproject.toml) 和 [frontend/package.json](/Users/congming/github/goldenshare/frontend/package.json) 为准，不在此复制版本表。

## 本地 Web 与运营前端

以下仅说明已有环境中的启动入口，不包含 Wealth 独立前端或 DG 的启动流程。

先确认依赖已就绪、已有进程、环境文件和数据库目标。配置样例见 [.env.example](/Users/congming/github/goldenshare/.env.example) 与 [.env.web.example](/Users/congming/github/goldenshare/.env.web.example)；不要覆盖已有本机配置。“本地启动”不意味着连接本地数据库。

获得启动授权后，在仓库根目录的既有 Python 环境中运行 Web：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local python3 -m src.app.web.run
```

另一个终端运行运营前端：

```bash
npm --prefix frontend run dev
```

默认访问 `http://127.0.0.1:5173/app/`；[Vite 配置](/Users/congming/github/goldenshare/frontend/vite.config.ts)将 `/api` 代理至 `http://127.0.0.1:8000`。后端端口改动时需核对代理目标。

已构建的运营前端也可由 Web 托管，在相应环境访问 `/app`；若配置了 `FRONTEND_DEV_SERVER_URL`，Web 优先重定向到开发服务器，未配置才读取构建产物。已有 Python 命令入口 `goldenshare-web` 与模块入口作用相同，环境配置仍需明确。

[本地/生产操作边界](/Users/congming/github/goldenshare/docs/release/local-prod-operation-boundary-v1.md)统一说明一键脚本、单侧启动、配置及授权。特别注意：一键脚本在缺少 frontend/node_modules 时会自动安装依赖；未经批准不能用它隐式安装。

## 数据库、任务与发布

- `goldenshare init-db` 在 [CLI](/Users/congming/github/goldenshare/src/cli.py) 中调用 Alembic `upgrade head`，是数据库迁移，不是只读检查或每次启动前的必要步骤。先核实目标库、当前版本、待执行迁移及授权；历史迁移可能包含删除数据。
- Web 提供页面/API；Ops Scheduler 生成任务请求，Worker 执行任务。仅启动 Web 不代表数据维护任务会执行。进程及生产服务管理见[正式发版流程](/Users/congming/github/goldenshare/docs/release/release-process-v1.md)，不要为文档验证顺手启动连接生产的 worker/scheduler。
- 小范围维护验证也会写数据，只有在目标与范围获准后才通过任务中心执行，并核对任务详情和实际写入结果。创建管理员账号、修改配置同样不是默认 smoke 步骤。
- 生产发版、服务权限、分支选择、迁移/seed 副作用和验收只在正式发版流程维护；本页不再提供一条脱离上下文的部署命令。

## 数据集研发与维护入口

数据集事实见 [DatasetDefinition 定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions)。定义、执行计划、源请求参数和运行观测各有职责，不能把全部规则归给某一个对象，也不能把 TaskRun 写成执行器的输出终点。

- [Definition 说明](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)：数据集事实及消费者。
- [执行计划说明](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)：请求解析、规划和执行职责。
- [Ops 当前契约](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)：TaskRun 编排、观测和运营入口。
- [数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)：Prod 数据集方案与验收；是否提供手动/自动维护依当前能力合同，不能一概要求所有数据集拥有相同入口。

### top_list

业务身份、来源版本、批内选择策略与追溯字段统一见 [top_list 维护说明](/Users/congming/github/goldenshare/docs/architecture/top-list-business-identity-and-source-version-plan-v1.md)。其中 `variant_count` 是本次 writer batch 的版本数，不是历史累计数。历史迁移 `20260507_000099` 包含删表重建，不能当作日常修复步骤重跑；回补也需另行批准。

### dividend 与 stk_holdernumber

以下是当前代码合同速记，不是源接口实测或生产完整性证明。定义与写入目标见 [low_frequency.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/low_frequency.py)。

| 数据集 | 当前 Raw → Serving | 有效键与字段边界 |
| --- | --- | --- |
| dividend | raw_tushare.dividend → core_serving.equity_dividend | row_key_hash 用于记录级幂等，event_key_hash 用于事件分组；必填业务字段为 ts_code/end_date/ann_date/div_proc，record_date/ex_date 可空 |
| stk_holdernumber | raw_tushare.holdernumber → core_serving.equity_holder_number | row_key_hash 用于记录级幂等，event_key_hash 按 ts_code/end_date 分组；必填业务字段为 ts_code/end_date，ann_date 可空 |

两者 Raw/Serving 模型均保留代理 id；Serving 的 event_key_hash 不是唯一键。分红不能以可空的 record_date/ex_date 直接组成主键，但这些日期仍参与记录 hash，不能理解成完全不参与身份。

[行转换](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)先做规范化和 hash；分红“实施”且 ex_date 缺失时，按送股/现金分红及已有日期条件补值，再生成 hash。具体算法见 [dividend_hash.py](/Users/congming/github/goldenshare/src/foundation/services/transform/dividend_hash.py) 与 [holdernumber_hash.py](/Users/congming/github/goldenshare/src/foundation/services/transform/holdernumber_hash.py)。

[Normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)在进入标准化批次前执行必填校验并记录拒绝原因，不能继续沿用“Raw 全收、只在 Core 拒绝”的旧承诺；具体写入与拒绝策略由当前 [Writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)决定。

### 历史 hash 修复工具：不是升级必跑步骤

代码仍存在，但硬编码目标是旧 schema，与上表当前目标不同：

| 工具 | 脚本硬编码目标 |
| --- | --- |
| [repair_dividend_hashes.py](/Users/congming/github/goldenshare/src/scripts/repair_dividend_hashes.py) | raw.dividend、core.equity_dividend |
| [repair_holdernumber_hashes.py](/Users/congming/github/goldenshare/src/scripts/repair_holdernumber_hashes.py) | raw.holdernumber、core.equity_holder_number |

两者均全表读入内存，重算 hash，按 row_key_hash 去重保留最大 id，**删除其余重复行**，更新保留行，入口最后提交事务；没有日期范围或 dry-run 参数。不是“只补字段”的无损工具，也不能通过直接替换 schema 就认定适用于现行数据。

本页仅保留追溯与风险说明，不提供默认执行指令，不删除或改造工具。如确需使用，必须另行核实实际表、数据用途与去重影响，按仓库数据操作规则确认逐表清单、备份方案及授权。本轮未核验这些旧表是否仍在、是否有人调用脚本，不据此作清退结论。

## 验证与文档维护

- 前端按[回归与基线流程](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md)选择检查；不在 README 再维护一份容易漂移的完整门禁。
- 后端按[Foundation 研发基线](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)和目标目录规则选回归，纯文档修改不要求启动业务服务。
- 文档执行 `python3 scripts/check_docs_integrity.py` 与 `git diff --check`。脚本只扫描 docs 下的规定内容，**不覆盖本根 README**；本页修改须另外检查本地链接及涉及的当前代码。完整覆盖边界见[文档维护基线](/Users/congming/github/goldenshare/docs/governance/docs-maintenance-baseline-v1.md)。
