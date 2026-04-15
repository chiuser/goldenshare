# Core 表统一为 Serving 语义方案 v1

更新时间：2026-04-15  
适用环境：停机切换（当前无下游流量）  
目标：把“对上服务语义”统一收口到 `core_serving.*`，避免 `core.*` 同时承载基础层与服务层造成混淆。

## 当前实施状态（2026-04-15）

已完成：
1. 第一批 `core -> core_serving` 收口已完成并上线验证通过。
2. `core.*` 指向 `core_serving.*` 的兼容视图已清理完成。
3. 部署脚本已默认禁用 pager，发版不再卡在 `(END)`。

本轮已迁入 `core_serving` 的表（37）：
- `security_serving`
- `equity_daily_bar`
- `equity_daily_basic`
- `stk_period_bar`
- `stk_period_bar_adj`
- `index_daily_serving`
- `index_weekly_serving`
- `index_monthly_serving`
- `trade_calendar`
- `hk_security`
- `us_security`
- `index_basic`
- `index_daily_basic`
- `index_weight`
- `etf_basic`
- `etf_index`
- `fund_daily_bar`
- `equity_moneyflow`
- `equity_top_list`
- `equity_block_trade`
- `equity_limit_list`
- `equity_dividend`
- `equity_holder_number`
- `ths_index`
- `ths_member`
- `ths_daily`
- `ths_hot`
- `dc_index`
- `dc_member`
- `dc_daily`
- `dc_hot`
- `kpl_list`
- `kpl_concept_cons`
- `limit_list_ths`
- `limit_step`
- `limit_cpt_list`
- `broker_recommend`

本轮明确暂不迁移（保留在 `core`）：
- `equity_indicators`（`ind_macd` / `ind_kdj` / `ind_rsi`）
- `equity_price_restore_factor`
- `equity_adj_factor`
- `fund_adj_factor`

---

## 1. 背景与问题

当前代码里已经有 `src/foundation/models/core_serving/*` 命名空间，但模型大多仍指向 `schema=core`。  
这会导致三个问题：

1. 语义混淆：同样叫 “serving 模型”，物理上却在 `core.*`。  
2. 运维成本高：Ops 页面、freshness、target_table 会混在 `core.*` 和少量 `*_serving` 名称中。  
3. 后续多源难扩展：`raw/std/serving` 分层在数据库层不够直观。

---

## 2. 自动盘点结果（基于当前代码）

按 `list_dataset_freshness_specs()` 扫描，当前共 44 个数据集：

- `raw_biying.*`：1 个（`biying_equity_daily`）
- `core.*`：41 个
- 其余（不经 freshness target_table）：2 个（派生/停用类）

其中“明显属于对上服务语义、建议迁到 `core_serving.*`”的优先清单如下：

1. `core.security_serving`
2. `core.equity_daily_bar`
3. `core.equity_adj_factor`
4. `core.equity_daily_basic`
5. `core.stk_period_bar`
6. `core.stk_period_bar_adj`
7. `core.index_daily_serving`
8. `core.index_weekly_serving`
9. `core.index_monthly_serving`
10. `core.ind_macd`
11. `core.ind_kdj`
12. `core.ind_rsi`

说明：以上是“先收口服务主链路”的最小闭环。`fund_daily_bar`、`fund_adj_factor`、`index_daily_basic`、`board/ranking` 可作为第二波。

---

## 3. 收口原则（明确边界）

1. `core_serving.*`：只放“对外查询/API 直接消费”的最终表。  
2. `core.*`：只放基础主数据、事件数据、中间事实、状态缓存等 Foundation 内部域。  
3. 停机切换阶段不保留长期双路径；若需要短期兜底，只允许临时 view（有截止时间）。

---

## 4. 目标结构（v1）

### 4.1 第一波迁移到 `core_serving`

- 行情与复权：`security_serving` / `equity_daily_bar` / `equity_adj_factor` / `equity_daily_basic`
- 周月线：`stk_period_bar` / `stk_period_bar_adj`
- 指数服务：`index_daily_serving` / `index_weekly_serving` / `index_monthly_serving`
- 技术指标：`ind_macd` / `ind_kdj` / `ind_rsi`

### 4.2 暂留 `core`（本轮不动）

- 基础主数据：`index_basic` / `etf_basic` / `etf_index` / `trade_calendar` / `hk_security` / `us_security`
- 低频事件与榜单：`equity_dividend` / `equity_holder_number` / `block_trade` / `moneyflow` / `top_list` / `limit_*` / `ths_*` / `dc_*` / `kpl_*`
- 指标状态与版本：`indicator_state` / `indicator_meta`
- 停用数据集：`equity_price_restore_factor`

---

## 5. 数据库切换方案（停机）

### 5.1 Pre-check

1. 确认服务已停：`web/worker/scheduler`  
2. 确认目标 schema 存在：

```sql
CREATE SCHEMA IF NOT EXISTS core_serving;
```

3. 确认目标表名不冲突（应为 0）：

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'core_serving'
  AND table_name IN (
    'security_serving','equity_daily_bar','equity_adj_factor','equity_daily_basic',
    'stk_period_bar','stk_period_bar_adj',
    'index_daily_serving','index_weekly_serving','index_monthly_serving',
    'ind_macd','ind_kdj','ind_rsi'
  );
```

### 5.2 迁移（元数据移动，不拷贝数据）

```sql
ALTER TABLE core.security_serving      SET SCHEMA core_serving;
ALTER TABLE core.equity_daily_bar      SET SCHEMA core_serving;
ALTER TABLE core.equity_adj_factor     SET SCHEMA core_serving;
ALTER TABLE core.equity_daily_basic    SET SCHEMA core_serving;
ALTER TABLE core.stk_period_bar        SET SCHEMA core_serving;
ALTER TABLE core.stk_period_bar_adj    SET SCHEMA core_serving;
ALTER TABLE core.index_daily_serving   SET SCHEMA core_serving;
ALTER TABLE core.index_weekly_serving  SET SCHEMA core_serving;
ALTER TABLE core.index_monthly_serving SET SCHEMA core_serving;
ALTER TABLE core.ind_macd              SET SCHEMA core_serving;
ALTER TABLE core.ind_kdj               SET SCHEMA core_serving;
ALTER TABLE core.ind_rsi               SET SCHEMA core_serving;
```

### 5.3 可选临时兼容（最多保留 7 天）

若需要先保老 SQL，可在 `core` 建同名 view：

```sql
CREATE VIEW core.equity_daily_bar AS SELECT * FROM core_serving.equity_daily_bar;
```

本方案默认不创建（直接收口）。

---

## 6. 代码改造清单

### 6.1 模型层

将以下模型的 `__table_args__ schema` 改为 `core_serving`：

- `src/foundation/models/core_serving/security_serving.py`
- `src/foundation/models/core_serving/equity_daily_bar.py`
- `src/foundation/models/core_serving/equity_adj_factor.py`
- `src/foundation/models/core_serving/equity_daily_basic.py`
- `src/foundation/models/core_serving/stk_period_bar.py`
- `src/foundation/models/core_serving/stk_period_bar_adj.py`
- `src/foundation/models/core_serving/index_daily_serving.py`
- `src/foundation/models/core_serving/index_weekly_serving.py`
- `src/foundation/models/core_serving/index_monthly_serving.py`
- `src/foundation/models/core_serving/ind_macd.py`
- `src/foundation/models/core_serving/ind_kdj.py`
- `src/foundation/models/core_serving/ind_rsi.py`

### 6.2 规格与运维

统一将 freshness / sync_state 里对应 target_table 改为 `core_serving.*`：

- `src/operations/specs/registry.py`
- `src/ops/queries/freshness_query_service.py`
- `src/operations/services/sync_job_state_reconciliation_service.py`

### 6.3 Biz 查询

确认所有行情读取都从 `core_serving.*` 取：

- `src/biz/queries/quote_query_service.py`

---

## 7. 测试与验收

### 7.1 单测回归（必须）

1. `tests/web/test_ops_freshness_api.py`
2. `tests/test_sync_job_state_reconciliation_service.py`
3. `tests/test_serving_*`
4. `tests/web/test_quote_api.py`（或 quote 相关集成测试）

### 7.2 数据验收（停机后）

1. 行数一致：

```sql
SELECT 'equity_daily_bar' AS table_name,
       (SELECT COUNT(*) FROM core_serving.equity_daily_bar) AS serving_rows;
```

2. 日期范围一致（迁移前后记录）：

```sql
SELECT MIN(trade_date), MAX(trade_date) FROM core_serving.equity_daily_bar;
```

3. 接口 smoke：

- `/api/v1/quote/detail/kline`
- `/api/v1/ops/freshness`
- `/app/ops/tushare` 数据源卡片

---

## 8. 回滚方案

若本轮出现问题，停机后执行反向迁移：

```sql
ALTER TABLE core_serving.equity_daily_bar SET SCHEMA core;
-- 其余表同理反向执行
```

再回滚代码到前一版本并重启服务。

---

## 9. 实施节奏建议

1. 第一步（当前）：先完成文档 + 表级清单确认。  
2. 第二步：提交一笔“schema 切换 + target_table 引用修正 + 测试”代码。  
3. 第三步：停机执行 DB 迁移 SQL，发布，做接口与页面验收。  
4. 第四步：补第二波（fund/index_daily_basic/board-rank）收口计划。
