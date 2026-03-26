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
goldenshare backfill-trade-cal --start-date 2010-01-01 --end-date 2026-03-24
goldenshare backfill-equity-series --resource daily --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource adj_factor --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource daily_basic --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource moneyflow --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource limit_list_d --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_week --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_month --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_adj_week --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_adj_month --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
```

说明：
- `backfill-*` 命令现在会输出逐单位进度，例如按证券或按交易日打印 `fetched/written`
- `limit_list_d` 按 Tushare 文档应从 `2020-01-01` 起回补，早于这个时间通常会空跑
- `stk_period_bar_week` / `stk_period_bar_month` / `stk_period_bar_adj_week` / `stk_period_bar_adj_month` 的历史回补统一走按 `ts_code` 纵向扫

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
goldenshare backfill-trade-cal --start-date 2010-01-01 --end-date 2026-03-24
goldenshare backfill-equity-series --resource daily --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource adj_factor --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_week --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_month --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_adj_week --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-equity-series --resource stk_period_bar_adj_month --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
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

为了兼容现有风格，`--ts-code` 仍可继续使用，但对 `index_weight` 来说它会被当作 `index_code` 处理。

指数扩展资源的历史回补也建议优先按代码维度执行，而不是按 `trade_date` 横向扫：

- `index_weekly` / `index_monthly` / `index_daily_basic`：按 `ts_code`
- `index_weight`：按 `index_code`

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
