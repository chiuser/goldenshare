# Core Serving + Serving Light 分层设计 v1

更新时间：2026-04-17  
适用范围：Foundation / Ops / Biz 三子系统  
目标：在保留 `core_serving` 业务契约层的前提下，新增轻量查询层 `core_serving_light`，实现“省空间 + 高性能 + 可扩展到多源”。

---

## 1. 背景与结论

当前我们已经完成了 `core_serving` 收口，业务接口逐步统一读取 `core_serving.*`。  
但在新增超宽数据集（例如技术面因子）时，若所有业务查询都直接扫超宽表，会出现：

1. I/O 与反序列化开销高，响应抖动明显。  
2. 存储空间压力大（尤其重复物化多层时）。  
3. 单源阶段需要“节省空间”，但又不能牺牲未来多源融合路径。

因此采用以下明确结论：

1. `raw` 必存完整数据（审计、回放、再加工依据）。  
2. `std` 在单源阶段可不物化。  
3. `core_serving` 保留为“业务契约层”，优先采用 `VIEW`（逻辑层，不额外占大空间）。  
4. 新增 `core_serving_light` 作为“性能层”（窄表或物化视图），承载高频查询。  
5. Biz 默认优先查 `core_serving_light`，不可用时回退 `core_serving`。

---

## 2. 分层职责（目标态）

### 2.1 `raw_<source>.*`（事实原始层）

1. 存完整字段，不做面向业务的裁剪。  
2. 保留源字段语义和追溯能力。  
3. 允许按源独立演进（`raw_tushare`、`raw_biying` 等）。

### 2.2 `core_serving.*`（业务契约层，逻辑优先）

1. 作为业务统一读取口径（字段命名、数据语义稳定）。  
2. 单源阶段优先使用 `VIEW`（直通 raw 或已存在的 serving 事实）。  
3. 多源阶段可逐步切换为实体表（`raw -> std -> resolution -> serving` 发布结果）。

### 2.3 `core_serving_light.*`（性能层）

1. 只保留高频查询字段。  
2. 用于接口低延迟场景（行情详情、列表快速检索、常用技术指标读取）。  
3. 可按数据集选择物化方式：
   - 小体量：物化视图（全量刷新可接受）
   - 大体量：实体表（增量 upsert，避免全量重算）

---

## 3. 设计边界（本期约束）

1. 不改变现有 pipeline mode 主框架（`single_source_direct` / `multi_source_pipeline` / `raw_only`）。  
2. 不强制所有数据集立刻落 `serving_light`，按“高频先行”逐步接入。  
3. 不将 `serving_light` 视为新的治理层级（它是 serving 的性能投影层，不替代 serving 契约）。  
4. 不在本期引入复杂双写事务；以“主链稳定 + 异步刷新 light”为主。

---

## 4. 数据路径定义

### 4.1 单源直出（当前主流）

```text
raw_tushare.<dataset>
  -> core_serving.<dataset> (VIEW 或现有实体)
  -> core_serving_light.<dataset_light> (窄表/物化视图)
```

说明：
1. `core_serving` 保证业务契约稳定。  
2. `core_serving_light` 保证查询性能。  
3. 两者语义一致，字段集合不同。

### 4.2 多源融合（后续扩展）

```text
raw_tushare/raw_biying
  -> core_multi.<dataset_std> (可物化)
  -> resolution policy
  -> core_serving.<dataset> (实体发布)
  -> core_serving_light.<dataset_light>
```

说明：本方案不阻断未来多源，只是在单源阶段避免无效存储膨胀。

---

## 5. 查询路由策略（Biz）

统一查询优先级：

1. 优先 `core_serving_light`。  
2. light 缺失/未命中时回退 `core_serving`。  
3. 专业明细接口可直接读 `core_serving`（明确声明）。

建议新增配置开关（服务端）：

1. `BIZ_USE_SERVING_LIGHT=true|false`（默认 `true`）  
2. `BIZ_SERVING_FALLBACK=true|false`（默认 `true`）

行为定义：

1. `BIZ_USE_SERVING_LIGHT=false`：完全读取 `core_serving`。  
2. `BIZ_USE_SERVING_LIGHT=true` 且 fallback 开启：light 失败不影响主服务可用性。

---

## 6. 刷新与一致性策略

### 6.1 触发方式

1. 数据集同步成功后，异步触发 `serving_light` 刷新任务。  
2. 支持手动重建命令（全量/区间）。  
3. 发布脚本可增加“缺失则初始化”但不强制每次全量刷新。

### 6.2 刷新粒度

1. 增量优先：按 `trade_date` / `ts_code` upsert。  
2. 全量重建仅用于：
   - 口径升级
   - 字段变更
   - 历史修复

### 6.3 一致性规则

1. `core_serving` 是语义真源；`serving_light` 是性能投影。  
2. 若两者冲突，以 `core_serving` 为准并触发 light 修复。  
3. 建议提供巡检命令：对账 `count/date-range/sample-hash`。

---

## 7. Ops 可观测要求

本方案落地后，Ops 至少需要补齐以下指标：

1. `light_enabled`：数据集是否启用轻量层。  
2. `light_last_refreshed_at`：最近刷新时间。  
3. `light_latest_business_date`：轻量层最新业务日期。  
4. `light_lag_seconds`：相对 `core_serving` 的延迟。  
5. `light_refresh_status`：最近一次刷新状态（成功/失败/跳过）。

任务中心建议新增任务类型（或规范命名）：

1. `refresh_serving_light.<dataset_key>`  
2. `rebuild_serving_light.<dataset_key>`

---

## 8. 存储与成本策略

### 8.1 建议原则

1. 宽字段进 raw，不在多层重复落同等宽度实体表。  
2. `core_serving` 尽量逻辑化（`VIEW` 优先），减少冗余复制。  
3. 仅把高频字段物化到 light。
4. 轻量层默认以“写入吞吐 + 空间效率”优先，不以高精度定点数为默认选型。

### 8.2 工程硬约束（必须遵守）

1. 数值类型默认使用 `DOUBLE PRECISION`（尤其技术指标、价格类浮点字段）。  
2. 避免大面积 `NUMERIC`（会显著增加磁盘占用与写入成本）。  
3. 按 `trade_date` 做 range 分区（优先年分区；超大表可月分区）。  
4. 主键统一：`(ts_code, trade_date)`。  
5. 必备索引：
   - `trade_date` 方向索引（按日同步/按日检索）
   - 如需按标的快速取近期序列，可补 `(ts_code, trade_date DESC)`。

推荐 DDL 形态（示意）：

```sql
CREATE TABLE core_serving_light.example_daily (
  ts_code VARCHAR(16) NOT NULL,
  trade_date DATE NOT NULL,
  close DOUBLE PRECISION,
  ma5 DOUBLE PRECISION,
  ma10 DOUBLE PRECISION,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ts_code, trade_date)
) PARTITION BY RANGE (trade_date);

CREATE INDEX idx_example_daily_trade_date
  ON core_serving_light.example_daily (trade_date);
```

### 8.3 何时使用实体 light 表

满足任一条件建议用实体表：

1. 单表行数大、接口访问频率高。  
2. 需要按时间增量更新，且全量 refresh 成本高。  
3. 需要独立索引优化（例如 `(ts_code, trade_date)` 复合索引）。

---

## 9. 推进计划（分阶段）

### Phase 1（试点）

1. 建立 `core_serving_light` schema。  
2. 选择 1 个高频数据集试点（建议行情/因子类）。  
3. 接入 Biz 查询优先 light + fallback serving。  
4. 验证时延、资源占用、错误回退。

### Phase 2（扩展）

1. 按访问热度逐个接入 light。  
2. 补齐 Ops 可观测与巡检命令。  
3. 固化开发模板（新增数据集时同步定义 light 口径）。

### Phase 3（治理收口）

1. 形成数据集级“契约字段清单 + light 字段清单”。  
2. 对低频数据集保持 `core_serving` 直读，不强制 light。  
3. 将 light 纳入发布验收（与 freshness 并列）。

---

## 10. 回滚与应急

1. 回滚开关：`BIZ_USE_SERVING_LIGHT=false`。  
2. 服务继续读取 `core_serving`，业务不受阻断。  
3. light 刷新任务可暂停，待修复后重跑。

---

## 11. 开发清单（执行时逐项勾选）

- [ ] 建立 `core_serving_light` schema 与命名规范  
- [ ] 定义首批试点数据集与字段口径  
- [ ] Biz 查询路由接入 `light -> serving` 回退机制  
- [ ] 新增/补齐 light 刷新任务  
- [ ] Ops 展示 light 状态指标  
- [ ] 增加 light 对账巡检命令  
- [ ] 更新数据集开发模板（新增“是否启用 light”章节）  
- [ ] 完成发布与回滚演练

---

## 12. 与现有规范关系

1. 继承 [Foundation 开发上手指南与历史遗留清单 v1](/Users/congming/github/goldenshare/docs/architecture/foundation-onboarding-and-legacy-checklist-v1.md) 中 pipeline mode 规则。  
2. 与 [子系统边界基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md) 的分层边界一致；本方案属于 serving 查询性能补充层。  
3. 与 [数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md) 联动，后续新增数据集必须声明是否启用 light。
