# goldenshare

PostgreSQL + Tushare 行情/选股系统第一期数据底座。

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
4. 先做小范围 smoke sync
5. 再执行历史同步或日常增量同步

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
goldenshare init-db
goldenshare sync-history --resources stock_basic --resources trade_cal
goldenshare sync-daily --resources daily_basic --resources moneyflow --resources limit_list_d
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

## 基础主数据类数据集接入模式

后续接入类似 `stock_basic` / `etf_basic` / `hk_basic` / `us_basic` 这种“基础主数据”接口时，统一按下面模式实现：

1. 显式声明 `fields`
   不依赖 Tushare 默认返回字段，所有输出字段都要在 [src/foundation/services/sync/fields.py](/Users/congming/github/goldenshare/src/foundation/services/sync/fields.py) 中定义常量并显式请求。像 `us_basic.enname` 这种默认不返回的字段，也必须包含进去。
2. raw/core 分层建表
   `raw.*` 负责保留原始接口输出和抓取元信息，`core.*` 负责提供规范化后的业务查询表。不要为了图省事把不同市场、不同语义的主数据硬塞进 [core.security](/Users/congming/github/goldenshare/src/foundation/models/core/security.py)。
3. sync service 最小转换
   基础主数据类资源通常不需要复杂 normalizer，只做日期转换、必要字段透传和 `source="tushare"` 这样的最小补充。
4. 运营后台完整打通
   新资源不仅要能 `sync-history`，还要同步接入：
   - ops catalog 参数定义
   - 手动任务
   - 自动任务
   - workflow
   - 数据状态 / freshness 展示
5. migration 保持 additive
   这类资源优先走“新增 raw/core 表和索引”的 additive migration，不碰无关表结构。

按这个模式，本轮新增了：
- `hk_basic` 港股列表
- `us_basic` 美股列表

## 日频榜单类数据集接入模式

后续接入类似 `ths_hot` / `dc_hot` / `kpl_list` / `limit_list_ths` / `limit_step` / `limit_cpt_list` 这种“日频榜单类”接口时，统一按下面模式实现：

1. 显式声明 `fields`
   和基础主数据一样，不依赖默认返回字段，所有输出字段都要在 [src/foundation/services/sync/fields.py](/Users/congming/github/goldenshare/src/foundation/services/sync/fields.py) 中定义并显式传给接口。
2. 按交易日同步与回补
   默认支持：
   - `sync_daily.<resource>` 按单个交易日同步
   - `backfill_by_trade_date.<resource>` 按交易日区间历史回补
3. raw/core 双表
   `raw.*` 记录原始榜单快照，`core.*` 提供查询表；必要时保留 `query_*` 请求上下文字段，避免多筛选条件下的数据语义丢失。
4. 用户参数只暴露高价值筛选项
   不要把文档里所有参数都直接暴露给运营后台。像单证券 `ts_code`、低频分析参数这类，如果日常同步价值很低，就不要放进手动任务和自动任务页面。
5. 多选参数优先复选框
   如果参数允许多值，前端统一用复选框，不再用下拉菜单；后端按接口语义决定是拼接传参还是拆分多次调用。

按这个模式，本轮新增了：
- `limit_list_ths` 同花顺涨跌停榜单
- `limit_step` 涨停天梯
- `limit_cpt_list` 最强板块统计

## 安全启动同步

建议按这个顺序启动同步，先确认库结构和小批量链路都正常，再开始大批量回补：

1. 先执行 migration
2. 先同步基础维表
3. 先跑最近 1 到 3 个交易日的 smoke sync
4. 确认日志、写入量、唯一键和字段映射都正常
5. 再执行大批量历史同步

最小 smoke 流程建议：

```bash
goldenshare init-db
goldenshare sync-history --resources stock_basic
goldenshare sync-history --resources trade_cal
goldenshare sync-daily --resources daily_basic --resources moneyflow --resources limit_list_d
goldenshare sync-daily --trade-date 2026-03-24 --resources top_list --resources block_trade
```

确认 smoke 正常后，再开始历史回补，例如：

```bash
goldenshare sync-history --resources etf_basic
goldenshare backfill-trade-cal --start-date 2010-01-01 --end-date 2026-03-24
goldenshare backfill-equity-series --resource daily --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource adj_factor --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-fund-series --resource fund_daily --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource daily_basic --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource moneyflow --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource limit_list_d --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_week --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_month --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_adj_week --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_adj_month --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-index-series --resource index_weekly --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-index-series --resource index_monthly --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-index-series --resource index_daily_basic --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-index-series --resource index_weight --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
```

新增的海外基础主数据可以这样同步：

```bash
goldenshare sync-history --resources hk_basic
goldenshare sync-history --resources hk_basic --list-status L
goldenshare sync-history --resources hk_basic --ts-code 00005.HK

goldenshare sync-history --resources us_basic
goldenshare sync-history --resources us_basic --classify EQT
goldenshare sync-history --resources us_basic --ts-code AAPL
```

说明：
- `backfill-*` 命令现在会输出逐单位进度，例如按证券或按交易日打印 `fetched/written`
- `limit_list_d` 按 Tushare 文档应从 `2020-01-01` 起回补，早于这个时间通常会空跑
- `stk_period_bar_week` / `stk_period_bar_month` / `stk_period_bar_adj_week` / `stk_period_bar_adj_month` 的历史回补统一走按 `ts_code` 纵向扫
- `fund_daily` 的历史回补走 `backfill-fund-series`，会从 `core.etf_basic` 读取 ETF/Fund 代码后按 `ts_code` 纵向扫；建议先执行 `goldenshare sync-history --resources etf_basic`
- `backfill-fund-series` 当前会默认跳过 `.OF` 结尾代码，因为基于现有数据库回补结果，`.OF` 代码在 `fund_daily` 中没有返回数据；命令会优先遍历 `*.SH` / `*.SZ` 等场内代码
- `backfill-index-series` 会从 `core.index_basic` 读取指数代码池，并按资源语义自动使用 `ts_code` 或 `index_code` 做纵向历史回补

## top_list reason_hash 切换顺序

`core.equity_top_list` 当前处于分阶段切换中：

- `reason_hash` 已写入 `core`
- 当前同步仍沿用旧主键语义做 upsert
- 还没有切到 `(ts_code, trade_date, reason_hash)` 冲突键

后续正确切换顺序：
1. 执行 `goldenshare init-db` 应用 migration
2. 执行 `python3 -m src.scripts.backfill_top_list_reason_hash` 回填历史 `reason_hash`
3. 运行冲突检查，确认不存在相同 `(ts_code, trade_date, reason_hash)` 的重复组
4. 最后单独一轮把 `top_list` 的 upsert 冲突键切到 `(ts_code, trade_date, reason_hash)`

## 最小启动顺序示例

新库初始化或已有库升级到最新版本：

```bash
goldenshare init-db
```

基础数据同步：

```bash
goldenshare sync-history --resources stock_basic
goldenshare sync-history --resources trade_cal
```

最近 1 到 3 个交易日的 smoke sync：

```bash
goldenshare sync-daily --resources daily_basic --resources moneyflow --resources limit_list_d
goldenshare sync-daily --trade-date 2026-03-24 --resources top_list --resources block_trade
```

确认无误后，再执行历史同步：

```bash
goldenshare sync-history --resources etf_basic
goldenshare backfill-trade-cal --start-date 2010-01-01 --end-date 2026-03-24
goldenshare backfill-equity-series --resource daily --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource adj_factor --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-fund-series --resource fund_daily --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_week --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_month --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_adj_week --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_adj_month --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-index-series --resource index_weekly --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-index-series --resource index_monthly --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-index-series --resource index_daily_basic --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-index-series --resource index_weight --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource daily_basic --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource moneyflow --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource limit_list_d --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
```

## 扩展资源说明

本轮新增的可同步资源名：

- `stk_period_bar_week`
- `stk_period_bar_month`
- `stk_period_bar_adj_week`
- `stk_period_bar_adj_month`
- `index_basic`
- `index_weekly`
- `index_monthly`
- `index_weight`
- `index_daily_basic`

`index_weight` 使用的是 Tushare 的 `index_code` 语义。CLI 里推荐显式传：

```bash
goldenshare sync-history --resources index_weight --index-code 000300.SH --start-date 2020-01-01 --end-date 2026-03-31
```

`index_weight` 仅支持 `--index-code`，不再接受 `--ts-code`。

指数扩展资源的历史回补现在可以直接使用：

```bash
goldenshare backfill-index-series --resource index_weekly --start-date 2020-01-01 --end-date 2026-03-29 --offset 0 --limit 100
goldenshare backfill-index-series --resource index_monthly --start-date 2020-01-01 --end-date 2026-03-29 --offset 0 --limit 100
goldenshare backfill-index-series --resource index_daily_basic --start-date 2020-01-01 --end-date 2026-03-29 --offset 0 --limit 100
goldenshare backfill-index-series --resource index_weight --start-date 2020-01-01 --end-date 2026-03-29 --offset 0 --limit 100
```

它会从 `core.index_basic` 读取指数代码池，然后按资源类型选择参数：

- `index_weekly` / `index_monthly` / `index_daily_basic`：按 `ts_code`
- `index_weight`：按 `index_code`

`fund_daily` 的历史回补与股票纵向回补分开，使用：

```bash
goldenshare sync-history --resources etf_basic
goldenshare backfill-fund-series --resource fund_daily --start-date 2024-01-01 --end-date 2026-03-29 --offset 0 --limit 100
```

其中 `backfill-fund-series` 会从 `core.etf_basic` 中读取 ETF/Fund 代码，并对每个 `ts_code` 调用 `fund_daily` 做分段历史写入。
当前实现会默认排除 `.OF` 结尾代码，以减少已经验证为空的无效请求。

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
python3 -m src.scripts.backfill_dividend_hashes
```

这样历史 `raw.dividend` 与 `core.equity_dividend` 记录都会补齐 hash 字段。

如果你本地之前已经跑过旧版 `dividend` 逻辑，先执行：

```bash
goldenshare init-db
```

再执行：

```bash
goldenshare backfill-low-frequency --resource dividend --offset 0 --limit 100
```

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
python3 -m src.scripts.backfill_holdernumber_hashes
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
