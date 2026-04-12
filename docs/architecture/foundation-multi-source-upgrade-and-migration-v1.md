# Foundation 多源数据基座升级与停机迁移方案 v1

更新时间：2026-04-12  
适用范围：`src/foundation/*`（本期不改 Ops 页面交互与 Ops 数据状态展示逻辑）  
关联基线：[current-architecture-baseline.md](/Users/congming/github/goldenshare/docs/architecture/current-architecture-baseline.md)

---

## 1. 背景与目标

当前数据基座以 Tushare 为主，模型与同步流程基本按“单源”建设。随着 Biying 等新源接入，必须将 Foundation 升级为“多源输入、统一输出”的架构：

- 对上层（Biz/Ops）输出统一业务语义，不暴露底层来源细节。
- 底层可接入多个源，并支持优先级、兜底、融合策略。
- 后续新增源时，不需要重做整套业务接口。

本方案聚焦 Foundation：

- 完成多源架构设计
- 设计一次性停机迁移方案（允许停机，不做双写/灰度）
- 明确与现有代码的冲突点与收敛路径

---

## 2. 现状梳理（基于当前源码）

## 2.1 同步框架现状

- 资源注册中心：`src/foundation/services/sync/registry.py`
  - `SYNC_SERVICE_REGISTRY` 以 `resource -> service class` 一对一映射。
- 基础同步抽象：`src/foundation/services/sync/resource_sync.py`
  - `HttpResourceSyncService`、`ProBarSyncService` 当前直接依赖 Tushare 客户端（`TushareHttpClient` / `TushareSdkClient`）。

结论：当前同步层没有“source adapter”抽象。

## 2.2 核心数据模型现状

典型表（如 `core.equity_daily_bar`）虽然有 `source` 字段，但主键仍是 `(ts_code, trade_date)`：

- [equity_daily_bar.py](/Users/congming/github/goldenshare/src/foundation/models/core/equity_daily_bar.py)

多数 core 表（如 `equity_adj_factor`, `equity_daily_basic`, `stk_period_bar`, `stk_period_bar_adj`）主键不含 source：

- [equity_adj_factor.py](/Users/congming/github/goldenshare/src/foundation/models/core/equity_adj_factor.py)
- [equity_daily_basic.py](/Users/congming/github/goldenshare/src/foundation/models/core/equity_daily_basic.py)
- [stk_period_bar.py](/Users/congming/github/goldenshare/src/foundation/models/core/stk_period_bar.py)
- [stk_period_bar_adj.py](/Users/congming/github/goldenshare/src/foundation/models/core/stk_period_bar_adj.py)

结论：多源数据无法“并存”，只能互相覆盖。

## 2.3 业务查询现状（读取耦合）

Biz 查询（K 线等）直接读 `core.*`，未引入来源维度选择：

- [quote_query_service.py](/Users/congming/github/goldenshare/src/biz/queries/quote_query_service.py)

结论：若底层引入多源且不改读层，会出现混源风险（例如日线来自 A，复权因子来自 B）。

---

## 3. 设计原则

1. 统一语义优先：对上只暴露统一业务模型，不透出源差异。
2. 多源并存优先：同一业务键可保留多个源版本，禁止覆盖式写入。
3. 策略驱动融合：主源优先、兜底补齐、字段级融合必须可配置。
4. 可审计：每条服务数据可追溯到来源记录与融合规则版本。
5. 可停机迁移：本期允许停机，追求方案干净，不保留长期临时兼容。

---

## 4. 目标架构（Foundation）

## 4.1 五层模型（详细版）

### 第一层：获取层（Ingestion）

职责：
- 对接外部数据源 API/SDK，完成请求调度与拉取。
- 屏蔽各数据源差异（认证、分页、频控、错误码）。

输入：
- `dataset_key`、时间窗口/游标、可选筛选参数（如 `ts_code`、`market`）。
- 来源配置（token、base_url、限流参数）。

输出：
- 标准化前的原始响应记录（内存对象）。
- 请求元数据（请求时间、分页信息、响应状态、重试次数）。

核心组件：
- `SourceConnector`（每源一个实现）
- `RequestPlanner`（分页/时间窗规划）
- `RateLimiter + RetryPolicy`（频控与重试）

失败处理：
- 可重试错误（超时、限流、5xx）按指数退避重试。
- 不可重试错误（鉴权失败、参数错误）直接失败并记录。
- 支持断点续跑（游标/分页续传）。

验收标准：
- 每个来源具备统一调用契约。
- 拉取日志可追溯到请求级别。

示例（股票日线）：
- 输入：`dataset_key=equity_daily_bar`，`source_key=biying`，`trade_date=2026-04-10`
- RequestPlanner 生成 1 次请求（按日单次）。
- 若 Biying 返回 429，则按 1s/2s/4s 退避重试，成功后返回原始 records 列表与请求元数据。

### 第二层：落地层（Landing Raw）

职责：
- 保真落库存档，原样保留来源数据，不做业务语义裁剪。
- 形成“可回放”的原始事实层。

输入：
- 获取层输出的原始记录 + 请求元数据。

输出：
- 分源 raw 表记录（例如 `raw_tushare.*`、`raw_biying.*`）。

核心组件：
- `RawWriter`
- `RawDedupPolicy`（按 `payload_hash/source_record_id` 控重复）
- `IngestAuditLogger`

失败处理：
- 批量写入失败可分片重试。
- 主键冲突按策略处理（忽略/更新/保留修订轨迹）。

验收标准：
- 原始字段不丢失，来源可回溯。
- 支持按时间与来源重放。

示例（股票日线）：
- `raw_tushare.equity_daily_bar_raw` 写入 4200 行，`source_key='tushare'`。
- `raw_biying.equity_daily_bar_raw` 写入 4198 行，`source_key='biying'`。
- 两边都保留 `payload_json`，后续可逐行复盘差异。

### 第三层：标准层（Canonical Std）

职责：
- 将不同来源字段映射到统一领域字段模型（字段名、类型、单位、代码格式）。
- 产出“按源标准化后”的一致事实，不做最终服务优选。

输入：
- 分源 raw 记录。
- 字段对齐矩阵与标准化规则版本。

输出：
- `core_multi.*_std` 标准事实表（保留 `source_key`）。

核心组件：
- `DatasetNormalizer`
- `SchemaValidator`
- `UnitConverter/CodeNormalizer`

失败处理：
- 单条脏数据隔离（写入错误队列或异常表，不阻断整批）。
- 规则失败记录 `rule_version` + 错误上下文。

验收标准：
- 字段类型与精度统一。
- 单位与代码规范统一。
- 可追溯到来源与规则版本。

示例（股票日线）：
- Biying 的 `symbol='SZ000001'` 统一转为 `ts_code='000001.SZ'`。
- Biying 的 `turnover` 单位为“元”，Tushare 的 `amount` 单位为“千元”，统一归一为“千元”。
- 结果写入 `core_multi.equity_daily_bar_std`，主键为 `(source_key, ts_code, trade_date)`。

### 第四层：融合层（Resolution）

职责：
- 基于策略从多源标准事实中选主、兜底、字段级融合。
- 解决同一业务键多来源冲突，产出唯一候选服务记录。

输入：
- `core_multi.*_std` 多源标准记录。
- `dataset_resolution_policy` 策略配置。

输出：
- 融合结果集（待发布到 serving），包含来源与策略命中信息。

核心组件：
- `PolicyEngine`
- `Resolver`（按数据集实现）
- `ConflictScorer`

失败处理：
- 冲突不可解时进入待人工审核队列。
- 策略失配时降级为主源优先并打告警。

验收标准：
- 每个业务键在融合结果中最多一条。
- 来源选择、字段取值可解释（可审计）。

示例（股票日线）：
- 同一键 `(000001.SZ, 2026-04-10)` 同时存在 tushare 与 biying。
- 策略为 `field_merge`：`open/high/low/close/amount` 用 biying，`turnover_rate` 用 tushare。
- 输出一条融合记录，并写入命中信息：`resolved_source_key='mixed'`、`resolved_policy_version=3`。

### 第五层：服务层（Serving）

职责：
- 向 Biz/Ops 提供稳定、统一、低复杂度查询表。
- 对外屏蔽来源与融合细节，但保留最小可追踪信息。

输入：
- 融合层结果。

输出：
- `core_serving.*` 服务表（对上读取口径）。

核心组件：
- `ServingBuilder`
- `ServingUpserter`
- `ServingHealthChecker`

失败处理：
- 服务表构建失败时不替换旧快照（原子切换）。
- 发布前后自动对账（行数、日期范围、关键字段抽样）。

验收标准：
- Biz/Ops 查询只依赖 serving 层即可完成业务功能。
- 服务层可稳定回滚到上一版本快照。

示例（股票日线）：
- `core_serving.equity_daily_bar` 对 `(ts_code, trade_date)` 永远只保留一条。
- Biz `GET /api/v1/quote/detail/kline` 不需要知道底层来源，直接读 serving。
- 若当天融合发布失败，保持上一版 serving 快照不替换。

## 4.2 `std` 与 `serving` 的定位边界

`std`（标准层）和 `serving`（服务层）不是重复层，职责严格不同：

- `std`：统一事实层
  - 目标：把不同来源的字段映射到统一语义，沉淀“按源标准化后的事实记录”。
  - 特性：仍保留 `source_key`，不做对外策略，不做最终优选。
  - 用途：审计、回放、复算、对账、策略变更后的重建输入。

- `serving`：对外发布层
  - 目标：基于策略（主源优先/兜底/字段融合）输出对上唯一口径。
  - 特性：一条业务键仅一条结果（例如 `(ts_code, trade_date)`），记录最终来源与策略版本。
  - 用途：Biz/Ops 统一读取，保证接口稳定。

为什么不直接 `raw -> serving`：

1. 直接耦合会把“数据标准化”和“业务策略”绑死，后续改策略要重跑全链路。  
2. 缺少中间事实层会导致审计困难，无法判断是清洗问题还是融合问题。  
3. 无法支持一个事实底座衍生多个服务口径（策略研究/展示/回测）。

例子：
- 同一个 `std` 可以同时构建：
  - `core_serving.equity_daily_bar`（产品行情口径）
  - `core_serving_research.equity_daily_bar`（研究口径，偏向完整字段）
- 若没有 `std`，每新增一个口径都要回到 raw 重写一套规则，风险高且难维护。

## 4.3 关键抽象

- `SourceConnector`：统一源适配器接口
- `DatasetNormalizer`：源字段 -> 标准字段映射
- `ResolutionPolicy`：多源融合规则
- `ServingBuilder`：按策略物化服务表

---

## 5. 数据模型设计（v1）

以下以“股票日线”为模板，其他数据集遵循同一模式扩展。

## 5.1 元数据与策略表（新增）

1. `foundation.source_registry`
- `source_key`（PK）例如 `tushare`, `biying`
- `display_name`
- `enabled`
- `priority`（默认优先级，数值越小优先）
- `config_json`
- `created_at/updated_at`

2. `foundation.dataset_resolution_policy`
- `dataset_key`（PK）例如 `equity_daily_bar`
- `mode`：`primary_fallback` / `freshness_first` / `field_merge`
- `primary_source_key`
- `fallback_source_keys`（json）
- `field_rules_json`（字段级策略）
- `version`
- `enabled`
- `updated_at`

3. `foundation.dataset_source_status`
- `dataset_key`
- `source_key`
- `is_active`
- `reason`
- `updated_at`
- 复合唯一键：`(dataset_key, source_key)`

示例数据：
- `source_registry`
  - `('tushare', 'Tushare Pro', enabled=true, priority=20)`
  - `('biying', 'Biying Market', enabled=true, priority=10)`
- `dataset_source_status`
  - `('equity_daily_bar','tushare',true,'')`
  - `('equity_daily_bar','biying',true,'')`

## 5.2 原始层（新增，示例）

`raw_multi.equity_daily_bar_raw`

- 主键：`(source_key, ts_code, trade_date, source_record_hash)`
- 关键字段：
  - `source_key`
  - `ts_code`
  - `trade_date`
  - `open/high/low/close/pre_close/change_amount/pct_chg/vol/amount`
  - `source_record_id`（可空）
  - `payload_json`
  - `payload_hash`
  - `ingested_at`

说明：
- 原始层允许重复（源侧多次修订），通过 hash/version 保留轨迹。

### 分源 raw 命名规则（强制）

为了明确来源边界并避免混表，raw 层采用“分源命名”：

- 推荐规则 A（按 schema 分源）：`raw_tushare.<dataset_raw>`、`raw_biying.<dataset_raw>`
- 推荐规则 B（按表名分源）：`raw.<dataset_raw>_tushare`、`raw.<dataset_raw>_biying`

二选一后全局统一，不可混用。  
本项目建议优先规则 A（schema 分源），便于权限隔离、迁移分批和运维观测。

关键约束：

1. 禁止将多个来源直接写入同一张 raw 表。  
2. raw 表字段允许不一致，禁止为“对齐字段”牺牲原始保真。  
3. 对齐动作统一在标准化流程进入 `core_multi.*_std` 时完成。

## 5.3 标准层（新增，示例）

`core_multi.equity_daily_bar_std`

- 主键：`(source_key, ts_code, trade_date)`
- 字段：
  - 标准业务字段（OHLCV 等）
  - `quality_score`
  - `normalized_at`
  - `rule_version`

说明：
- 该层是“按源标准化后”的事实层，仍保留 source。

## 5.4 服务层（新增，示例）

`core_serving.equity_daily_bar`

- 主键：`(ts_code, trade_date)`
- 字段：
  - 统一业务字段（OHLCV）
  - `resolved_source_key`（本条最终来源）
  - `resolved_policy_version`
  - `resolved_at`

说明：
- Biz 默认只读该表。
- 可通过 `resolved_source_key` 回溯来源。

## 5.5 字段对齐矩阵模板（新增数据集必填）

> 用途：在接入新来源前，先定义“源字段 -> 标准字段 -> 服务字段”的映射与规则，避免实现时歧义。

| 数据集 | 标准字段（`std/serving`） | 类型/精度 | Tushare 字段 | Biying 字段 | 对齐规则 | 缺失处理 | 备注 |
|---|---|---|---|---|---|---|---|
| equity_daily_bar | ts_code | string(16) | `ts_code` | `symbol` | 统一转 `ts_code` 标准格式 | 无则丢弃该行 | 主键字段 |
| equity_daily_bar | trade_date | date | `trade_date` | `date` | 统一转 UTC+8 交易日日期 | 无则丢弃该行 | 主键字段 |
| equity_daily_bar | open | numeric(18,4) | `open` | `open_price` | 十进制四位 | 缺失可空 |  |
| equity_daily_bar | high | numeric(18,4) | `high` | `high_price` | 十进制四位 | 缺失可空 |  |
| equity_daily_bar | low | numeric(18,4) | `low` | `low_price` | 十进制四位 | 缺失可空 |  |
| equity_daily_bar | close | numeric(18,4) | `close` | `close_price` | 十进制四位 | 缺失可空 |  |
| equity_daily_bar | pre_close | numeric(18,4) | `pre_close` | `prev_close` | 十进制四位 | 缺失可空 |  |
| equity_daily_bar | change_amount | numeric(18,4) | `change`/`change_amount` | `change` | 优先显式字段，缺失时计算 | 缺失可计算 |  |
| equity_daily_bar | pct_chg | numeric(10,4) | `pct_chg` | `pct` | 统一百分比语义 | 缺失可空 |  |
| equity_daily_bar | vol | numeric(20,4) | `vol` | `volume` | 单位统一（手/股） | 缺失可空 | 必填单位说明 |
| equity_daily_bar | amount | numeric(20,4) | `amount` | `turnover` | 单位统一（千元/元） | 缺失可空 | 必填单位说明 |

补充模板（字段级融合策略）：

| 数据集 | 字段 | 主来源 | 兜底来源 | 冲突规则 | 质量分规则 |
|---|---|---|---|---|---|
| equity_daily_bar | open/high/low/close | tushare | biying | 主源优先 | 若主源缺失且兜底存在则降权 |
| equity_daily_bar | vol/amount | tushare | biying | 主源优先 + 单位归一后比较 | 偏差超阈值打告警 |

## 5.6 冲突规则配置示例（可直接落库）

### 示例 A：默认主源优先（A 主 B 兜底）

```json
{
  "dataset_key": "equity_daily_bar",
  "mode": "primary_fallback",
  "primary_source_key": "tushare",
  "fallback_source_keys": ["biying"],
  "field_rules_json": {},
  "version": 1,
  "enabled": true
}
```

### 示例 B：B 覆盖 A（字段级覆盖，含 `amount`）

```json
{
  "dataset_key": "equity_daily_bar",
  "mode": "field_merge",
  "primary_source_key": "tushare",
  "fallback_source_keys": ["biying"],
  "field_rules_json": {
    "open": { "primary": "biying", "fallback": ["tushare"] },
    "high": { "primary": "biying", "fallback": ["tushare"] },
    "low": { "primary": "biying", "fallback": ["tushare"] },
    "close": { "primary": "biying", "fallback": ["tushare"] },
    "pre_close": { "primary": "biying", "fallback": ["tushare"] },
    "change_amount": { "primary": "biying", "fallback": ["tushare"] },
    "pct_chg": { "primary": "biying", "fallback": ["tushare"] },
    "vol": { "primary": "biying", "fallback": ["tushare"] },
    "amount": { "primary": "biying", "fallback": ["tushare"] },
    "turnover_rate": { "primary": "tushare", "fallback": ["biying"] }
  },
  "version": 2,
  "enabled": true
}
```

### 示例 C：时间新鲜度优先

```json
{
  "dataset_key": "equity_daily_bar",
  "mode": "freshness_first",
  "primary_source_key": "tushare",
  "fallback_source_keys": ["biying"],
  "field_rules_json": {
    "__meta__": {
      "freshness_window_seconds": 600,
      "tie_breaker": "priority"
    }
  },
  "version": 3,
  "enabled": true
}
```

说明：
- `mode` 可以后续新增，不影响历史版本。
- 任何规则更新都必须 `version+1`，并记录发布时间与发布人。

## 5.7 端到端示例（股票日线一次构建）

1. 获取层：拉取 tushare/biying 两源 `2026-04-10` 日线。  
2. 落地层：分别写入 `raw_tushare/raw_biying` 原始表。  
3. 标准层：统一字段后写入 `core_multi.equity_daily_bar_std`。  
4. 融合层：按策略 v2 生成统一结果。  
5. 服务层：upsert 到 `core_serving.equity_daily_bar`。  
6. 验收：检查当天行数、最大日期、关键股票抽样一致性。  

## 5.8 表结构全清单（首批改造范围）

说明：
- 本清单覆盖“首批多源改造范围”的全部数据表（股票主链路），作为编码前基线。
- 范围：`security + daily + adj + daily_basic + period + indicators` 及其 raw 表。
- 其他数据集（指数、ETF、板块、榜单等）沿用同模板在 v2 补充。

### A. 现有表（当前已存在）

| 表名 | 层级 | 当前主键 | 当前字段（完整） | 字段含义（摘要） | 改造后新增/调整 |
|---|---|---|---|---|---|
| `raw.stock_basic` | raw | `ts_code` | `ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,exchange,curr_type,list_status,list_date,delist_date,is_hs,act_name,act_ent_type,api_name,fetched_at,raw_payload` | 股票基础信息原始落地 | 不直接改；迁移为分源表 `raw_tushare.stock_basic_raw` / `raw_biying.stock_basic_raw` |
| `core.security` | core | `ts_code` | `ts_code,symbol,name,area,industry,fullname,enname,cnspell,market,exchange,curr_type,list_status,list_date,delist_date,is_hs,act_name,act_ent_type,security_type,source` | 统一股票主数据 | 保持对外语义；后续 serving 层可按策略输出 `core_serving.security` |
| `raw.daily` | raw | `ts_code,trade_date` | `ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount,api_name,fetched_at,raw_payload` | 股票日线原始行情 | 迁移为分源 raw；保留原样字段 |
| `core.equity_daily_bar` | core | `ts_code,trade_date` | `ts_code,trade_date,open,high,low,close,pre_close,change_amount,pct_chg,vol,amount,source` | 股票日线统一事实（单源时期） | 不再作为最终对外读取表；迁移后由 `core_serving.equity_daily_bar` 对外 |
| `raw.adj_factor` | raw | `ts_code,trade_date` | `ts_code,trade_date,adj_factor,api_name,fetched_at,raw_payload` | 复权因子原始数据 | 迁移为分源 raw |
| `core.equity_adj_factor` | core | `ts_code,trade_date` | `ts_code,trade_date,adj_factor` | 复权因子统一事实（旧） | 迁移后进入 `core_multi.equity_adj_factor_std` 并参与 serving 融合 |
| `core.equity_price_restore_factor` | core | `ts_code,trade_date` | `ts_code,trade_date,cum_factor,single_factor,event_applied,event_ex_date` | 价格还原因子（当前停用但保留） | 保持停用状态；不纳入首批 serving 输出 |
| `raw.daily_basic` | raw | `ts_code,trade_date` | `ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv,api_name,fetched_at,raw_payload` | 每日基本面原始数据 | 迁移为分源 raw |
| `core.equity_daily_basic` | core | `ts_code,trade_date` | `ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv` | 每日基本面统一事实 | 迁移后进入 `core_multi.equity_daily_basic_std` + `core_serving.equity_daily_basic` |
| `raw.stk_period_bar` | raw | `ts_code,trade_date,freq` | `ts_code,trade_date,freq,end_date,open,high,low,close,pre_close,vol,amount,change,pct_chg,api_name,fetched_at,raw_payload` | 周/月原始行情 | 迁移为分源 raw |
| `core.stk_period_bar` | core | `ts_code,trade_date,freq` | `ts_code,trade_date,freq,end_date,open,high,low,close,pre_close,vol,amount,change_amount,pct_chg` | 周/月不复权统一事实 | 迁移后进入 `core_multi.stk_period_bar_std` + `core_serving.stk_period_bar` |
| `raw.stk_period_bar_adj` | raw | `ts_code,trade_date,freq` | `ts_code,trade_date,freq,end_date,open,high,low,close,pre_close,open_qfq,high_qfq,low_qfq,close_qfq,open_hfq,high_hfq,low_hfq,close_hfq,vol,amount,change,pct_chg,api_name,fetched_at,raw_payload` | 周/月复权原始行情 | 迁移为分源 raw |
| `core.stk_period_bar_adj` | core | `ts_code,trade_date,freq` | `ts_code,trade_date,freq,end_date,open,high,low,close,pre_close,open_qfq,high_qfq,low_qfq,close_qfq,open_hfq,high_hfq,low_hfq,close_hfq,vol,amount,change_amount,pct_chg` | 周/月复权统一事实 | 迁移后进入 `core_multi.stk_period_bar_adj_std` + `core_serving.stk_period_bar_adj` |
| `core.ind_macd` | core | `ts_code,trade_date,adjustment,version` | `ts_code,trade_date,adjustment,version,dif,dea,macd_bar` | MACD 指标结果 | 迁移后新增来源维度（通过 std/serving 分层承载） |
| `core.ind_kdj` | core | `ts_code,trade_date,adjustment,version` | `ts_code,trade_date,adjustment,version,k,d,j` | KDJ 指标结果 | 同上 |
| `core.ind_rsi` | core | `ts_code,trade_date,adjustment,version` | `ts_code,trade_date,adjustment,version,rsi_6,rsi_12,rsi_24` | RSI 指标结果 | 同上 |
| `core.indicator_state` | core | `ts_code,adjustment,indicator_name,version` | `ts_code,adjustment,indicator_name,version,last_trade_date,state_json` | 指标递推状态缓存 | 建议增加 `source_key`（见下） |
| `core.indicator_meta` | core | `indicator_name,version` | `indicator_name,version,params_json` | 指标参数版本元数据 | 保留；建议增加 `scope`（可选）区分数据源策略 |

### B. 改造后新增表（首批）

| 表名 | 层级 | 计划主键 | 计划字段（完整） | 字段含义（摘要） |
|---|---|---|---|---|
| `foundation.source_registry` | meta | `source_key` | `source_key,display_name,enabled,priority,config_json,created_at,updated_at` | 来源注册与默认优先级 |
| `foundation.dataset_resolution_policy` | meta | `dataset_key` | `dataset_key,mode,primary_source_key,fallback_source_keys,field_rules_json,version,enabled,updated_at` | 数据集融合策略定义 |
| `foundation.dataset_source_status` | meta | `dataset_key,source_key` | `dataset_key,source_key,is_active,reason,updated_at` | 数据集-来源可用状态 |
| `raw_tushare.equity_daily_bar_raw` / `raw_biying.equity_daily_bar_raw` | raw | `source_key,ts_code,trade_date,source_record_hash` | `source_key,ts_code,trade_date,open,high,low,close,pre_close,change_amount,pct_chg,vol,amount,source_record_id,payload_json,payload_hash,ingested_at` | 分源原始日线保真层 |
| `core_multi.equity_daily_bar_std` | std | `source_key,ts_code,trade_date` | `source_key,ts_code,trade_date,open,high,low,close,pre_close,change_amount,pct_chg,vol,amount,quality_score,rule_version,normalized_at` | 按源标准化日线事实层 |
| `core_serving.equity_daily_bar` | serving | `ts_code,trade_date` | `ts_code,trade_date,open,high,low,close,pre_close,change_amount,pct_chg,vol,amount,resolved_source_key,resolved_policy_version,resolved_at` | 对外统一日线服务层 |
| `core_multi.equity_adj_factor_std` | std | `source_key,ts_code,trade_date` | `source_key,ts_code,trade_date,adj_factor,quality_score,rule_version,normalized_at` | 按源标准化复权因子 |
| `core_serving.equity_adj_factor` | serving | `ts_code,trade_date` | `ts_code,trade_date,adj_factor,resolved_source_key,resolved_policy_version,resolved_at` | 对外统一复权因子 |
| `core_multi.equity_daily_basic_std` | std | `source_key,ts_code,trade_date` | `source_key,ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv,quality_score,rule_version,normalized_at` | 按源标准化 daily_basic |
| `core_serving.equity_daily_basic` | serving | `ts_code,trade_date` | `ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv,resolved_source_key,resolved_policy_version,resolved_at` | 对外统一 daily_basic |
| `core_multi.indicator_macd_std` | std | `source_key,ts_code,trade_date,adjustment,version` | `source_key,ts_code,trade_date,adjustment,version,dif,dea,macd_bar,rule_version,computed_at` | 按源标准化 MACD |
| `core_serving.ind_macd` | serving | `ts_code,trade_date,adjustment,version` | `ts_code,trade_date,adjustment,version,dif,dea,macd_bar,resolved_source_key,resolved_policy_version,resolved_at` | 对外统一 MACD |

### C. 现有表的“新增字段”建议清单（用于过渡期兼容）

| 表名 | 建议新增字段 | 用途 | 是否强制 |
|---|---|---|---|
| `core.indicator_state` | `source_key` | 区分不同来源的递推状态，避免状态串线 | 是 |
| `core.indicator_meta` | `scope`（如 `global/source_key`） | 参数版本可按来源/全局区分 | 否（建议） |
| `core.*` 旧单源事实表 | `deprecated_at`（仅元数据层记录亦可） | 标记读路径迁移状态 | 否（建议） |

---

## 5.9 字段演进流程（受控加列，不做临时改表）

目标：支持“新来源出现新字段”时，稳定对上透出且可回滚。

### 步骤 1：字段提案

输入：
- 字段名、业务语义、单位、精度、空值规则、计算口径、是否可索引。

输出：
- 字段评审记录（建议落在数据集开发文档）。

示例：
- 新字段：`avg_trade_price`
- 语义：当日成交额/成交量的均价
- 单位：元
- 类型：`numeric(18,4)`

### 步骤 2：对齐矩阵更新

- 在“字段对齐矩阵”中增加该字段在各来源的映射与缺失处理。
- 明确是否参与融合策略与冲突规则。

### 步骤 3：Schema 变更（Alembic）

- 按层新增字段：先 `std`，再 `serving`（必要时 raw 保留 payload 不强制加列）。
- 迁移脚本必须可回滚。

### 步骤 4：规则与代码实现

- normalizer 支持字段映射与单位归一。
- resolver 增加字段级策略（主源/兜底/冲突处理）。
- serving builder 增加字段发布与 provenance。

### 步骤 5：数据回填与对账

- 对历史窗口执行回填（按数据集策略决定范围）。
- 对账指标：
  - 字段非空率
  - 与来源抽样差异
  - 单位归一正确性

### 步骤 6：对外发布

- Biz API 新字段采用向后兼容方式发布（新增字段不破坏旧客户端）。
- 发布后观察期内保留快速回滚开关。

### 步骤 7：版本化管理

- 策略版本 `version+1`
- 记录变更人、时间、影响数据集、回滚方案。

---

---

## 6. 与现有代码的冲突点与收敛策略

## 6.1 同步客户端冲突

现状：`resource_sync.py` 写死 Tushare。  
收敛：引入 `SourceConnectorFactory`，同步服务按 `source_key` 获取 connector。

## 6.2 表主键冲突

现状：多数 core 表主键不含 source。  
收敛：不在原表硬改主键，采用“新 schema 新表”（`raw_multi/core_multi/core_serving`），避免大规模 DDL 风险。

## 6.3 读取路径冲突

现状：Biz 直接读 `core.*`。  
收敛：迁移后 Biz 切到 `core_serving.*`；旧 `core.*` 保留只读窗口，最终下线。

## 6.4 复权/指标链路一致性冲突

现状：复权因子、指标与日线读取存在隐式同源前提。  
收敛：复权、指标也必须进入 `*_multi` + `core_serving` 同源融合链路，禁止跨层混搭。

---

## 7. 目录与代码结构调整建议（Foundation 内）

新增模块建议：

```text
src/foundation/
  connectors/
    base.py
    tushare_connector.py
    biying_connector.py
    factory.py
  normalization/
    equity_daily_bar_normalizer.py
    ...
  resolution/
    policy_engine.py
    resolvers/
      equity_daily_bar_resolver.py
      ...
  serving/
    builders/
      equity_daily_bar_builder.py
      ...
```

现有 `services/sync/*` 可逐步改造为：
- 调用 connector 拉取
- 落 raw_multi
- 调用 normalizer 写 core_multi
- 触发 resolver/builder 更新 core_serving

---

## 8. 停机迁移方案（一次性切换）

本方案符合“可停机、无双写、无灰度”的约束。

## 8.1 迁移前准备（T-1 到 T-0）

1. 冻结发布
- 冻结 `main` 写入；仅允许迁移分支提交。

2. 准备迁移包
- Alembic DDL：新增 schema/table/index
- 数据迁移脚本：旧表 -> 新表
- 对账脚本：行数、范围、抽样一致性

3. 备份演练
- 在预发环境完整演练一次“迁移 + 回滚”。

## 8.2 正式停机窗口（T 时刻）

1. 停服务
- 停 `goldenshare-web`
- 停 `ops-worker`
- 停所有定时触发

2. 全量备份
- 物理备份（整库）
- 逻辑备份（关键 schema：`raw/core/ops/app`）

3. 执行 DDL
- 创建 `raw_multi/core_multi/core_serving/foundation`（或项目确定命名）
- 创建元数据与策略表

4. 历史数据回灌
- 将旧 `core`/`raw` 数据回灌到 `*_multi`
- 统一标记 `source_key='tushare_legacy'`

5. 构建服务层
- 按 policy 生成 `core_serving.*`
- 首版 policy：`primary_fallback` 且主源 `tushare_legacy`

6. 对账与回归
- SQL 对账（见 8.4）
- 业务接口回归（K 线/详情/基础信息）

7. 切换读取
- Biz/Foundation 读取入口改指向 `core_serving.*`

8. 启动服务
- 启动 worker
- 启动 web
- 执行健康检查

## 8.3 回滚方案（仍在停机窗口内）

触发条件：任一核心对账失败或关键接口回归失败。

回滚步骤：
1. 停服务（保持停机）
2. 回滚代码到迁移前 tag
3. 恢复数据库备份
4. 重启服务
5. 记录失败原因并进入下一次窗口

注意：回滚必须整包，不做半回滚。

## 8.4 对账清单（必须全部通过）

1. 行数对账
- 对关键数据集比较 `旧 core` 与 `core_serving` 的记录数（按日期段/按股票抽样）。

2. 键覆盖对账
- `(ts_code, trade_date)` 覆盖率必须达到 100%（允许已知停牌缺失规则外）。

3. 日期范围对账
- 最小/最大 `trade_date` 一致。

4. 数值抽样对账
- 随机抽样 N 只股票 * M 天，OHLCV 一致（保留小数精度容差）。

5. 链路一致性对账
- 复权与指标计算读取的基础行情来源必须一致（同一 `resolved_source_key`）。

---

## 9. 分阶段实施范围（Foundation）

## 9.1 v1 范围（本次）

- 完成多源基础框架与元数据策略表
- 覆盖股票主链路：
  - 日线（`daily`）
  - 复权因子（`adj_factor`，价格还原因子后续按策略接入）
  - 技术指标（`equity_indicators`）
  - 周月线（`stk_period_bar*`）
- Biz 读取切到 `core_serving` 对应表

## 9.2 v2 范围（后续）

- 扩展到指数、ETF、板块、榜单、低频事件
- 支持字段级融合策略（不仅主源兜底）
- 增加来源质量评分自动化

---

## 10. Ops 对接边界（先声明，后续单独方案）

本文件不展开 Ops 改造实现，仅给 Foundation 对接边界：

1. Ops 未来需要在数据状态中支持 source 维度观测。
2. JobSpec 未来需支持 source 选择或策略选择（默认可隐藏）。
3. 健康度需支持“按来源”与“融合后服务口径”双视图。
4. 停用策略可扩展到 `(dataset_key, source_key)` 级别。

---

## 11. 风险清单与控制

1. 风险：多源数据口径冲突导致融合错误  
控制：策略表版本化 + 抽样回放 + 人工审核白名单

2. 风险：迁移耗时超窗口  
控制：预演估时 + 分数据域批量导入 + 索引延后创建

3. 风险：读取切换后隐式依赖旧表  
控制：启动前执行 SQL 探针，确认 Biz 查询仅访问 `core_serving`

4. 风险：复权/指标链路混源  
控制：在指标任务中强制校验 `resolved_source_key` 一致性

---

## 12. 决策结论

1. Foundation 从“单源数据集维护”升级为“多源数据产品基座”。
2. 采用“多层架构 + 策略融合 + 服务统一输出”。
3. 采用一次性停机迁移，不做双写，不做灰度。
4. 本期先完成 Foundation，Ops 多源管理在下一文档单独落地。
