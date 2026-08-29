# ETF 激活池历史 LLD 与退场实现记录 v1

状态：历史 LLD；P3-P8 的消费者迁移与代码退场已完成，P11 生产 drop 已完成
创建日期：2026-06-18
退场更新：2026-08-29
上位历史记录：[ETF 激活池历史设计与退场记录 v1](/Users/congming/github/goldenshare/docs/architecture/etf-active-pool-design-plan-v1.md)
现行编码依据：[ETF 基础信息重建与下游数据审计清理 LLD v1](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md)

本文不再提供旧池的可执行类、SQL、CLI 或 API 设计。旧实现细节只按退场审计所需的粒度保留。

## 1. 旧实现边界

退场前基础设施由以下层次组成：

```text
ops.etf_series_active
-> EtfSeriesActive ORM / model registry
-> EtfSeriesActiveDAO / DAOFactory.etf_series_active
-> EtfSeriesActiveStore / OpsEtfSeriesActiveStore
-> EtfSeriesActiveSeedService
-> goldenshare ops-seed-etf-series-active
```

主键是 `(resource, ts_code)`。旧 seed service 负责 resource、后缀和固定数量校验；旧 Review API/UI 只读展示池内容。该链已无运行时消费者，并在 P8 从当前代码中整体删除。

## 2. 替代契约

现行代码只通过 `EtfBasicDAO` 取得 ETF 请求资格：

| 形态 | 用途 |
| --- | --- |
| `load_requestability_snapshot(as_of_date, exchange)` | 一次 planner、Health 或实时批次冻结一份资格集合 |
| `get_requestable_target(ts_code, as_of_date, exchange)` | 显式单代码、监控池写入和 ETF 级规则门禁 |
| `requestable_targets_subquery(as_of_date, exchange)` | 候选分页的 count/page 查询复用同一关系子句 |

资格条件只在 DAO 中实现。planner、writer、API 和监控服务不得自行拼 `list_status/list_date/exchange` 条件。

## 3. 消费者迁移账本

| 阶段 | 代码结果 | 负向门禁 |
| --- | --- | --- |
| P3 | `etf_mins/etf_sh_cons/etf_sz_cons` 改用 Basic；切窗起点不早于 `list_date` | Definition 与 planner 不再出现旧 resource |
| P4 | `fund_daily` raw 与 serving 分两阶段提交；serving 使用 Basic | selector/serving 失败不能回滚 raw；旧 cleanup 删除 |
| P5 | realtime Health 改为 `eligible_etf_count/eligible_snapshot_count` | 旧 `active_*` 字段无 alias |
| P6 | `/eligible-etfs`、pool/re-enable、ETF rule、runtime 使用 Basic | 旧 `/active-etfs` 为 404；运行时不回退旧池 |
| P7 | ETF Review API/UI、schema、路由、导航删除 | 两条旧 Review GET 地址为 404 |
| P8 | 旧基础设施、seed CLI、装配和专属测试删除 | 新退场测试固定无 ORM/DAOFactory/CLI，且指数池仍存在 |

## 4. P8 文件级结果

已删除：

```text
src/foundation/dao/etf_series_active_dao.py
src/foundation/kernel/contracts/etf_series_active_store.py
src/ops/etf_series_active_store_adapter.py
src/ops/models/ops/etf_series_active.py
src/ops/services/etf_series_active_seed_service.py
```

同步从 `DAOFactory`、`src.ops.models.ops`、App model registry、主 CLI 和 Ops handler 删除旧装配与命令。五份只证明旧能力存在的 model/DAO/seed/CLI/report 测试一并删除；Web 测试 fixture 不再创建旧表，实时监控反例只使用 Basic 不可请求行。

必须保留：

```text
ops.index_series_active
IndexSeriesActive / IndexSeriesActiveDAO / index store adapter
ops.etf_realtime_monitor_pool
ops.etf_realtime_monitor_rule
ops.etf_realtime_alert
ops.etf_realtime_minute_stat
```

## 5. Migration 契约

历史 create migration 原样保留：

```text
20260618_000117_add_etf_series_active.py
```

P8 在开工时确认唯一 Alembic head 为 `20260828_000156`，因此新增：

```text
20260829_000157_drop_etf_series_active.py
revision = 20260829_000157
down_revision = 20260828_000156
```

upgrade 只调用：

```text
drop_table("etf_series_active", schema="ops")
```

downgrade 抛出 `RuntimeError`，明确不可逆。禁止 `CASCADE`、`IF EXISTS`、自动重建、seed 恢复或把旧行迁移到新表。

## 6. 测试与静态规则

`tests/test_etf_series_active_retirement.py` 固定以下事实：

1. model registry 没有旧 ETF model，但仍注册指数池。
2. `DAOFactory` 没有 `etf_series_active`，但仍有 `index_series_active`。
3. 旧 seed 命令无法调用且不出现在 CLI help。
4. migration 只 drop 精确旧表，不触碰指数池。
5. downgrade 明确失败，历史 create migration 仍存在。

静态清零按语义执行：生产代码、前端和配置中旧 ETF model/DAO/contract/adapter/seed/CLI 必须为零；测试只允许退场负向断言；Alembic 只允许历史 create 与新 drop migration；历史文档中的旧名称必须明确标注为历史证据。`list_active_codes` 和 `active_pool_count` 不能全仓机械清零，因为指数能力和明确退场断言仍合法使用这些普通词。

## 7. 发布边界

P8 没有执行生产 migration。P11 独立授权后，生产已升至 `20260829_000157`，精确 drop 已生效，旧表不存在，指数池仍正常。drop 后不支持回滚到依赖旧池的版本，只允许前向修复 Basic selector 或其消费者。
