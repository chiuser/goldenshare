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
goldenshare sync-history --resources stock_basic trade_cal
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
```

说明：
- `backfill-*` 命令现在会输出逐单位进度，例如按证券或按交易日打印 `fetched/written`
- `limit_list_d` 按 Tushare 文档应从 `2020-01-01` 起回补，早于这个时间通常会空跑

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
goldenshare backfill-by-trade-date --resource daily_basic --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource moneyflow --start-date 2010-01-01 --end-date 2026-03-24 --offset 0 --limit 20
goldenshare backfill-by-trade-date --resource limit_list_d --start-date 2020-01-01 --end-date 2026-03-24 --offset 0 --limit 20
```
