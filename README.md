# goldenshare

PostgreSQL + Tushare 行情/选股系统数据运营平台。

## 技术栈

- Python 3.13+
- PostgreSQL
- SQLAlchemy 2.0
- Alembic
- Pydantic
- Typer
- Tushare
- React
- TypeScript
- Vite
- Mantine
- TanStack Query
- TanStack Router

## 快速开始

1. 创建虚拟环境并安装依赖
2. 配置环境变量
3. 执行数据库 migration
4. 启动 Web 与前端
5. 在任务中心创建小范围数据维护任务做 smoke 验证

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
goldenshare init-db
```

## 环境变量

见 `.env.example`。

Web 环境相关变量见 `.env.web.example`。

## 前端应用一期

仓库现在已经接入了新的前端应用骨架，位置在 [frontend/package.json](/Users/congming/github/goldenshare/frontend/package.json) 所在目录。

这套前端应用当前先挂在 `/app`，目的是：

- 先把未来长期使用的前端技术栈搭起来
- 不立即破坏已上线的 `/platform-check` 和 `/ops`
- 让运维系统成为第一批迁移试验田

相关设计文档：

- [frontend-technology-and-component-selection.md](/Users/congming/github/goldenshare/docs/frontend/frontend-technology-and-component-selection.md)
- [frontend-application-phase1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-application-phase1.md)
- [dataset-catalog.md](/Users/congming/github/goldenshare/docs/datasets/dataset-catalog.md)

### 本地开发

1. 启动后端 Web：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local python3 -m src.app.web.run
```

2. 启动前端 dev server：

```bash
cd frontend
npm install
npm run dev
```

3. 浏览器访问：

```text
http://127.0.0.1:5173/app/
```

说明：

- `vite.config.ts` 已经把 `/api` 代理到 `http://127.0.0.1:8000`
- `.env.web.example` 里也预留了 `FRONTEND_DEV_SERVER_URL`

### 构建并由 FastAPI 托管

如果你希望直接由 FastAPI 托管前端构建产物，可以执行：

```bash
cd frontend
npm install
npm run build
```

然后启动后端：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local python3 -m src.app.web.run
```

此时访问：

```text
http://127.0.0.1:8000/app
```

### 前端验证命令

```bash
cd frontend
npm run typecheck
npm run test
npm run build
```

## 数据库升级方式

`goldenshare init-db` 的真实语义是：对当前配置的数据库执行 Alembic migration 到最新版本，也就是等价于项目内封装的 `alembic upgrade head`。

这意味着它适用于两种场景：

- 新库初始化
  数据库已经创建好，但还没有任何业务表时，执行 `goldenshare init-db`，会把 schema 和表结构建到最新版本。
- 已有库升级
  数据库里已经有旧版本表结构时，执行 `goldenshare init-db`，会把已有库升级到最新 migration。

如果你已经在当前 Python 环境里安装了项目依赖，也可以直接使用：

```bash
alembic upgrade head
```

项目内推荐统一使用：

```bash
goldenshare init-db
```

## 数据集定义与维护入口

数据集的身份、输入参数、日期模型、枚举、多选、分层写入目标和维护规划，统一从 [src/foundation/datasets/definitions](/Users/congming/github/goldenshare/src/foundation/datasets/definitions) 下的 `DatasetDefinition` 落账。

数据维护执行链统一为：

```text
DatasetDefinition
-> DatasetActionRequest
-> DatasetExecutionPlan
-> IngestionExecutor
-> TaskRun
```

接入或调整数据集时，必须遵守：

1. 先补齐 `DatasetDefinition`，不允许页面、查询层或执行层自行拼装事实字段。
2. 输入参数、枚举、多选、日期模型、分页、扇出、事务策略和写入目标，只能从 Definition 派生。
3. 运维后台只消费后端已经收口好的字段，不在前端重新推断数据集名称、最近维护日期、状态或处理范围。
4. 新数据集必须接入任务中心手动任务、任务记录、任务详情和数据源卡片状态展示。
5. smoke 验证优先通过 Web 任务中心创建小范围维护任务；命令行只保留薄入口，不能作为独立事实源。

## top_list 版本保留口径

`top_list` 现已按“业务身份 / 来源版本”两层事实收口：

- `reason_hash` 表示同一个龙虎榜业务事件
- `payload_hash` 表示该业务事件的某一个来源版本
- `raw_tushare.top_list` 按 `(ts_code, trade_date, reason, payload_hash)` 保留来源版本
- `core_serving.equity_top_list` 继续按 `(ts_code, trade_date, reason_hash)` 保留一条业务事实
- serving 同时记录：
  - `selected_payload_hash`
  - `variant_count`
  - `resolution_policy_version`

当前 V1 版本选择规则只有一条硬规则：

- 同一 `reason_hash` 下，若 `float_values` 一条为空、一条非空，优先保留非空值版本
- 其它数值冲突先保守保持当前最后一条口径，同时通过 `variant_count + selected_payload_hash` 保证后续可追溯

注意：

- `20260507_000099` 这条 migration 会直接删除并重建 `top_list` 的 raw / serving 表
- 历史 `top_list` 数据不会在 migration 中回填，升级后必须按需要重跑对应日期窗口

详细设计见：

- [top-list-business-identity-and-source-version-plan-v1.md](/Users/congming/github/goldenshare/docs/architecture/top-list-business-identity-and-source-version-plan-v1.md)

## 最小启动顺序示例

新库初始化或已有库升级到最新版本：

```bash
goldenshare init-db
```

数据维护 smoke 验证：

1. 启动 Web 和前端。
2. 进入任务中心的手动任务页。
3. 选择一个小范围数据集与时间点。
4. 提交后在任务记录和任务详情中确认状态、处理范围、阶段进展和数据源卡片状态。

## 扩展资源说明

数据集清单、输入参数和日期模型以 `DatasetDefinition` 为准。新增或调整资源时，不在 README 复制一份第二事实源；需要查看当前事实时，优先看 [src/foundation/datasets/definitions](/Users/congming/github/goldenshare/src/foundation/datasets/definitions)。

## dividend 说明

`dividend` 这条链路已经按真实业务语义调整过键设计：

- `raw.dividend`
- `core.equity_dividend`

当前分层规则是：

- `raw.dividend`
  - 使用 `row_key_hash` 做记录级幂等入湖
  - 目标是尽量保留 Tushare 原始返回，不因为业务关键字段缺失而丢数据
- `core.equity_dividend`
  - 使用 `row_key_hash` 做记录级幂等写入
  - 同时保存 `event_key_hash` 用于后续按事件聚合同一分红事项

这样做的原因是：

- `div_proc = 预案` 时，`record_date` 和 `ex_date` 可能为空
- 因此不能再把 `record_date/ex_date` 当成主键组成部分

现在的行为是：

- `raw` 会尽量保留全部返回记录
- `预案` 记录可以正常写入
- `record_date/ex_date` 允许为空
- 缺少 `ts_code/end_date/ann_date/div_proc` 的记录不会进入 `core`，并记录汇总 warning

如果你是在已经跑过旧版 `dividend` 逻辑的库上升级，建议在 migration 后执行一次：

```bash
python3 -m src.scripts.repair_dividend_hashes
```

这样历史 `raw.dividend` 与 `core.equity_dividend` 记录都会补齐 hash 字段。

如果你本地之前已经跑过旧版 `dividend` 逻辑，先执行：

```bash
goldenshare init-db
```

再通过任务中心创建 `dividend` 小范围维护任务，确认写入和状态展示正常。

## holdernumber 说明

`stk_holdernumber` 这条链路也按和 `dividend` 相同的分层原则调整过：

- `raw.holdernumber`
  - 使用代理主键和 `row_key_hash`
  - 尽量保留所有合法返回，即使 `ann_date` 为空
- `core.equity_holder_number`
  - 使用代理主键、`row_key_hash` 和 `event_key_hash`
  - 只要求最小业务条件 `ts_code` 与 `end_date`

如果你是在已经跑过旧版 `stk_holdernumber` 逻辑的库上升级，先执行：

```bash
goldenshare init-db
```

如需对历史数据补齐 hash，可执行：

```bash
python3 -m src.scripts.repair_holdernumber_hashes
```

## Web 平台一期

Web 平台一期当前只包含平台基础设施，不包含业务页面和业务 API。

建议先准备一份 Web 环境文件：

```bash
cp .env.web.example .env.web.local
```

这里的“local”指本地运行 Web 服务的开发场景，不强制要求连接本地数据库。
如果你的开发方式是“本地 Web + 远程数据库”，可以直接把远程数据库连接写入 `.env.web.local`。

本地开发启动前设置：

```bash
export GOLDENSHARE_ENV_FILE=.env.web.local
```

本地一键“编译 + 启动”（推荐）：

```bash
bash scripts/local-build-and-run.sh
```

该脚本会默认执行：

1. 后端编译检查（`compileall`）
2. 前端构建（`npm run build`）
3. 同时启动 Web（`8000`）与前端 dev server（`5173`）

初始化或升级数据库：

```bash
goldenshare init-db
```

创建一个用于平台验证的管理员账号：

```bash
python3 -m src.scripts.create_user --username admin --password your_password --admin
```

启动 Web：

```bash
python3 -m src.app.web.run
```

或者直接使用安装后的命令：

```bash
goldenshare-web
```

如果只想启动单侧服务，可用：

```bash
bash scripts/local-build-and-run.sh --web-only
bash scripts/local-build-and-run.sh --frontend-only
```

启动后可访问：

- `/api/docs`
- `/api/health`
- `/platform-check`

如果要让运维系统里的自动任务和手动同步任务真正跑起来，还需要单独启动调度器和执行器：

```bash
goldenshare ops-scheduler-serve
goldenshare ops-worker-serve
```

推荐把三类进程分开运行：

- Web：页面和 API
- Scheduler：扫描自动任务，生成任务请求
- Worker：消费任务请求，真正执行同步 / 回补 / 维护

平台回归测试：

```bash
pytest tests/web
```

说明：

- `.env.web.example` 是 Web 平台环境变量模板
- `scripts/goldenshare-web.service` 提供了一个 systemd 部署样例
- `scripts/goldenshare-ops-scheduler.service` 提供了调度器部署样例
- `scripts/goldenshare-ops-worker.service` 提供了执行器部署样例
- `scripts/deploy-systemd.sh` 提供了面向 systemd 托管服务器的发版脚本
- `scripts/goldenshare-deploy.sudoers` 提供了 `goldenshare` 用户无密码重启相关服务的 sudoers 样例
- `tests/web` 和 `/platform-check` 是平台防腐层，后续新增 Web 功能或修改平台能力时都必须回归验证

生产发版建议：

- 不要在服务器上手工运行 `python -m src.app.web.run` 或 `goldenshare ops-worker-serve`
- Web、Scheduler、Worker 应统一交给 systemd 管理
- 如果需要由 `goldenshare` 用户直接执行发版脚本，请先安装 `scripts/goldenshare-deploy.sudoers`
- 发版脚本示例：

```bash
bash scripts/deploy-systemd.sh main
```
