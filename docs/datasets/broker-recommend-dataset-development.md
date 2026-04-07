# 券商每月荐股（`broker_recommend`）数据集开发说明

## 1. 背景与目标

- 数据集名称：券商每月荐股
- 资源 key：`broker_recommend`
- 所属域：基础主数据
- 本次目标（新增/扩展/修复）：新增数据集，完成 raw/core 全字段落库，并打通运营后台（可执行、可观测、可诊断）

## 2. 接口来源

- 数据源平台：Tushare Pro
- 官方文档链接（必须可访问）：<https://tushare.pro/document/2?doc_id=267>
- API 名称：`broker_recommend`
- 文档版本/抓取日期：2026-04-06（按 doc_id=267 页面内容核对）

## 3. 接口能力分析

### 3.1 输入参数（上游原生）

| 参数名 | 类型 | 是否必填 | 说明 | 是否纳入运营筛选 |
| --- | --- | --- | --- | --- |
| `month` | `str` | 是 | 月度，格式 `YYYYMM` | 是（用户侧以 `YYYY-MM` 选择，系统自动归一化） |
| `limit` | `int` | 否 | 单次返回条数（文档约束单次最多 1000） | 否（系统内部分页参数） |
| `offset` | `int` | 否 | 分页起始偏移 | 否（系统内部分页参数） |

### 3.2 输出字段（上游原生）

| 字段名 | 类型（文档） | 业务含义 | 是否全量落库 |
| --- | --- | --- | --- |
| `month` | `str` | 月度 | 是 |
| `currency` | `str` | 币种 | 是 |
| `name` | `str` | 股票名称 | 是 |
| `ts_code` | `str` | 股票代码 | 是 |
| `trade_date` | `str` | 收盘日期 | 是 |
| `close` | `float` | 收盘价 | 是 |
| `pct_change` | `float` | 月涨跌幅 | 是 |
| `target_price` | `float` | 目标价 | 是 |
| `industry` | `str` | 所属行业 | 是 |
| `broker` | `str` | 券商 | 是 |
| `broker_mkt` | `str` | 市场标识 | 是 |
| `author` | `str` | 分析师 | 是 |
| `recom_type` | `str` | 评级类型 | 是 |
| `reason` | `str` | 推荐理由 | 是 |

### 3.3 同步策略结论

- 是否支持单日同步：否（该接口为月度接口，无 `trade_date`）
- 是否支持历史回补：是（按月份序列循环调用）
- 默认调度策略（如有）：建议“每月 1~3 日自动执行一次当月同步”（接口文档描述该时段更新）
- 需要的级联依赖（例如先同步 A 再同步 B）：无
- 分页策略：每个月份调用时，按 `limit=1000` + `offset` 分页循环，直到返回为空或少于 `limit`

## 4. 表设计（Raw/Core）

## 4.1 `raw.broker_recommend`

- 主键策略：组合主键（`month`, `ts_code`, `broker`）
- 字段清单：
  - 业务字段：`month`, `currency`, `name`, `ts_code`, `trade_date`, `close`, `pct_change`, `target_price`, `industry`, `broker`, `broker_mkt`, `author`, `recom_type`, `reason`, `offset`
  - 审计字段：`api_name`, `fetched_at`, `raw_payload`

## 4.2 `core.broker_recommend`

- 主键策略：组合主键（`month`, `ts_code`, `broker`）
- 字段清单：与 raw 业务字段一致，另含 `created_at`, `updated_at`
- 索引策略：
  - `idx_broker_recommend_month`
  - `idx_broker_recommend_trade_date`
  - `idx_broker_recommend_ts_code_month`
- 与其他核心表关联关系（如有）：
  - `ts_code` 可关联 `core.security.ts_code`（逻辑关联，非强制外键）

## 5. 同步实现设计

- Sync Service：`SyncBrokerRecommendService`（`HttpResourceSyncService`）
- 参数构建规则（UI意图 -> 执行参数）：
  - 单月维护：`month=YYYYMM`
  - 历史回补：`start_month/end_month` 在任务层转换为月份序列，逐月调用 `month=YYYYMM`
  - 每个月份内部再执行分页：`limit=1000, offset=0,1000,2000...`
- 日期/数值/枚举归一化规则：
  - `month` 统一存 `YYYYMM` 字符串（不转 `date`）
  - 字段去空格、空字符串转 `NULL`
- 幂等写入策略（upsert key）：`(month, ts_code, broker)`
- 失败重试与异常分类：
  - 复用现有 HTTP 重试与限流
  - 上游错误透传摘要（避免长堆栈污染页面）

## 6. 运维接入设计（Ops）

- 任务规格（job spec）：
  - `sync_daily.broker_recommend`：单月维护（参数 `month`）
  - `backfill_by_month.broker_recommend`：月份区间回补（`start_month` + `end_month`）
  - `sync_history.broker_recommend`：保留全量入口（默认无参数）
- 是否支持：手动执行 / 自动调度 / 重试 / 停止
  - 手动执行：是
  - 自动调度：是（建议月频）
  - 重试：是
  - 停止：是
- 手动表单字段（用户视角，不暴露底层内部参数）：
  - 模式：`单月维护` / `历史回补`
  - 单月维护：`月份选择器（YYYY-MM）`（仅年/月，不可选具体日）
  - 历史回补：`开始月份`、`结束月份`（均为年/月选择器，不可选具体日）
  - 不向用户暴露 `limit/offset`，由系统自动分页
- 数据状态归类：基础主数据
- 新鲜度观测方式：
  - 业务日期范围：该数据集不按日观测，页面展示“最近同步日期”
  - 最近同步日期：`last_sync_date`

## 7. 对外接口影响（Biz/API）

- 是否新增业务接口：本期否（先入基座与运维）
- 是否影响现有接口字段：否
- 兼容性说明：增量新增，不影响现有数据集与 API 行为

## 8. 数据质量与校验

- 字段完整性校验：
  - `month`、`broker`、`ts_code` 必须非空
- 主键冲突与去重策略：
  - 按 `(month, ts_code, broker)` upsert
- 空值策略（允许/不允许）：
  - `name` 允许为空（上游偶发缺失时保留记录）
- 与上游对账方式：
  - 按月统计条数对账（接口返回行数 vs core upsert 影响行）
  - 抽样核对券商与股票代码组合

## 9. 测试与验收

### 9.1 测试清单

- 单元测试：
  - 参数构建（`month`）
  - 月份序列生成（回补）
  - upsert 主键幂等
- 集成测试：
  - 单月同步任务可执行
  - 月度回补任务可执行
  - 任务停止/重试状态正确
- 回归测试：
  - 运营页任务列表可见
  - 数据状态页可见且新鲜度计算正确

### 9.2 验收标准

- [ ] raw/core 全字段落库完成
- [ ] 任务可在运营台可见并可执行
- [ ] 数据状态页可观测
- [ ] 失败可诊断，日志可读
- [ ] 文档与实现一致

## 10. 发布与回滚

- 迁移脚本：
  - 新建 `raw.broker_recommend`
  - 新建 `core.broker_recommend`
  - 新增索引与唯一约束
- 发布顺序：
  - 数据库迁移 -> 同步服务注册 -> 任务规格接入 -> 前端表单接入 -> 验证
- 回滚策略：
  - 回滚代码到前一版本
  - 保留新表（不删历史数据）；必要时停用对应 job spec
- 风险点与应对：
  - 风险：接口月初更新延迟
  - 应对：状态页标记“月频数据”，避免误判为日频滞后

## 11. 当前支持范围（交付快照）

- 当前已支持能力：
  - 文档级设计完成（待实现）
  - 明确单月维护 + 月份回补策略
- 暂不支持能力（及原因）：
  - 暂不提供业务侧消费 API（先完成基座与运维）
- 后续迭代计划：
  - 与研究报告类数据联动，形成券商观点主题视图
