# Ops Legacy Spec Key 清洗与恢复 Runbook（V1）

## 目标

把历史遗留的旧执行键（`sync_daily.*` / `sync_history.*` / `backfill_*.*` / `sync_minute_history.*`）一次性清洗为统一语义：

- `spec_type = dataset_action`
- `spec_key = <dataset_key>.maintain`

并阻断后续再次写入旧键。

---

## 影响范围（字段）

1. `ops.job_execution.spec_key`
2. `ops.job_schedule.spec_key`
3. `ops.dataset_status_snapshot.primary_execution_spec_key`
4. `ops.job_execution_step.step_key`
5. `ops.job_execution_unit.unit_id`
6. `ops.job_execution_event.unit_id`
7. `ops.config_revision.before_json/after_json`（`job_schedule` 的 `spec_key/spec_type`）

---

## 数据恢复（先备份后迁移）

> 先执行备份，再执行 Alembic 迁移 `20260426_000073`。

### 1. 生成备份标签

建议格式：`YYYYMMDD_HHMMSS`，例如 `20260426_041500`。

### 2. 建备份表（仅备份命中旧键的数据）

```sql
-- 请将 ${backup_tag} 替换为实际标签

CREATE TABLE ops.legacy_spec_backup_${backup_tag}_job_execution AS
SELECT *
FROM ops.job_execution
WHERE spec_key ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.';

CREATE TABLE ops.legacy_spec_backup_${backup_tag}_job_schedule AS
SELECT *
FROM ops.job_schedule
WHERE spec_key ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.';

CREATE TABLE ops.legacy_spec_backup_${backup_tag}_dataset_status_snapshot AS
SELECT *
FROM ops.dataset_status_snapshot
WHERE primary_execution_spec_key ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.';

CREATE TABLE ops.legacy_spec_backup_${backup_tag}_job_execution_step AS
SELECT *
FROM ops.job_execution_step
WHERE step_key ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.';

CREATE TABLE ops.legacy_spec_backup_${backup_tag}_job_execution_unit AS
SELECT *
FROM ops.job_execution_unit
WHERE unit_id ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.';

CREATE TABLE ops.legacy_spec_backup_${backup_tag}_job_execution_event AS
SELECT *
FROM ops.job_execution_event
WHERE unit_id ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.';

CREATE TABLE ops.legacy_spec_backup_${backup_tag}_config_revision AS
SELECT *
FROM ops.config_revision
WHERE object_type = 'job_schedule'
  AND (
    COALESCE(before_json->>'spec_key', '') ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.'
    OR COALESCE(after_json->>'spec_key', '') ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.'
  );
```

---

## 执行迁移

执行 Alembic 到最新版本，包含：

- 数据清洗：`20260426_000073_normalize_ops_legacy_spec_keys.py`
- 结构约束：新增 check constraints，阻断旧键回流

---

## 验收 SQL（必须全为 0）

```sql
WITH legacy AS (
  SELECT 'ops.job_execution.spec_key' AS field, count(*) AS cnt
  FROM ops.job_execution
  WHERE spec_key ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.'

  UNION ALL
  SELECT 'ops.job_schedule.spec_key', count(*)
  FROM ops.job_schedule
  WHERE spec_key ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.'

  UNION ALL
  SELECT 'ops.dataset_status_snapshot.primary_execution_spec_key', count(*)
  FROM ops.dataset_status_snapshot
  WHERE primary_execution_spec_key ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.'

  UNION ALL
  SELECT 'ops.job_execution_step.step_key', count(*)
  FROM ops.job_execution_step
  WHERE step_key ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.'

  UNION ALL
  SELECT 'ops.job_execution_unit.unit_id', count(*)
  FROM ops.job_execution_unit
  WHERE unit_id ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.'

  UNION ALL
  SELECT 'ops.job_execution_event.unit_id', count(*)
  FROM ops.job_execution_event
  WHERE unit_id ~ '^(sync_daily|sync_history|sync_minute_history|backfill_trade_cal|backfill_equity_series|backfill_by_trade_date|backfill_by_date_range|backfill_by_month|backfill_fund_series|backfill_index_series|backfill_low_frequency)\.'
)
SELECT * FROM legacy ORDER BY field;
```

---

## 业务侧验证

1. 在数据源卡片点击“去操作”，URL 参数应是：
   - `spec_type=dataset_action`
   - `spec_key=<dataset>.maintain`
2. 手动任务页 Step1 的“数据分组 / 维护对象”能自动回填。
3. 执行详情页与今日运行页不再出现 `sync_daily.*`、`backfill_*.*`、`sync_history.*` 文案。
