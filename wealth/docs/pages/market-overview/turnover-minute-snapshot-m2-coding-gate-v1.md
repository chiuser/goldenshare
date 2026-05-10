# 市场总览｜成交额总览分钟线快照 M2 编码前门禁 v1

> 用途：在编码前冻结“turnover 分钟线快照改造”的表结构、命令、读写切换、回归范围。  
> 阶段：分钟线快照长期方案开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [成交额总览标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-benchmark-requirement-v1.md)
2. [成交额总览技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-implementation-design-v1.md)
3. [成交额总览分钟线快照长期方案 v1（HTML）](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-minute-snapshot-plan-v1.html)

---

## 1. 目的

1. 本门禁对应范围：`turnover` 模块分钟线快照长期改造
2. 本门禁目标：解决 `/api/v1/wealth/market/turnover` 对 `raw_tushare.stk_mins` 的结构性慢查询
3. 本门禁不做：
   - 不改 `turnover` 页面 UI
   - 不改 `turnover` 顶层 API 路径与响应字段
   - 不扩散到 `money-flow`、`breadth`、`leaderboard` 等其他模块
   - 不引入自动触发、Redis、raw fallback

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 快照表结构冻结
2. [ ] 主键与维度冻结（含 `type`）
3. [ ] `points_json` 结构冻结
4. [ ] 首期频率范围冻结（`1/5/15/30/60`）
5. [ ] 手动物化命令语义冻结
6. [ ] 构建状态与观测字段冻结
7. [ ] 页面读取链路冻结（只读 snapshot）
8. [ ] raw fallback 明确禁用
9. [ ] 回补/重建幂等规则冻结
10. [ ] 消费者审计清单冻结
11. [ ] 性能预算冻结
12. [ ] 验证与回滚策略冻结
13. [ ] 签字完成

---

## 3. 表结构冻结

### 3.1 目标表

```sql
core_serving.wealth_market_turnover_snapshot
```

### 3.2 主键与维度

```text
PRIMARY KEY (type, market, trade_date, freq)
```

字段冻结：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `type` | `varchar(16)` | 是 | 主体类型；首期固定 `stock` |
| `market` | `varchar(16)` | 是 | 市场标识；首期固定 `CN_A` |
| `trade_date` | `date` | 是 | 交易日 |
| `freq` | `smallint` | 是 | 分钟频率；首期 `1/5/15/30/60` |
| `latest_trade_time` | `timestamp` | 是 | 该切片最新分钟点；例：`2026-05-08 15:00:00` |
| `security_count` | `integer` | 是 | 参与汇总的证券数 |
| `source_row_count` | `bigint` | 是 | 本次物化读取的原始分钟行数，仅用于对账与排障 |
| `total_amount` | `numeric(20,2)` | 是 | 当日该频率下最终总成交额，单位 `thousand_yuan`（千元） |
| `total_vol` | `bigint` | 是 | 当日该频率下最终总成交量，整数 |
| `points_json` | `jsonb` | 是 | 日内点序列 |
| `build_status` | `varchar(16)` | 是 | `READY/FAILED` |
| `build_version` | `varchar(32)` | 是 | 当前物化逻辑版本 |
| `built_at` | `timestamptz` | 是 | 最近一次构建完成时间 |
| `build_note` | `text` | 否 | 构建备注/失败摘要 |

### 3.3 约束冻结

1. `type in ('stock', 'index', 'sector')`
2. `market` 首期只允许 `CN_A`
3. `freq in (1,5,15,30,60)`
4. `points_json` 默认空数组，不允许 `NULL`
5. `build_status` 首期只允许 `READY/FAILED`

---

## 4. `points_json` 结构冻结

```json
[
  {
    "tradeTime": "09:30",
    "tradeTimeTs": "2026-05-08 09:30:00",
    "amount": 123456.79,
    "vol": 3456789,
    "securityCount": 5187
  }
]
```

冻结规则：

1. 存该频率下**完整的日内点序列**，不是只存页面当前展示点
2. 序列按 `tradeTimeTs` 升序
3. `tradeTime` 供前端直接展示
4. `tradeTimeTs` 供后端/调试精确判断
5. `amount` 为该分钟点成交额，单位 `thousand_yuan`（千元），不是累计值
6. `vol` 为该分钟点成交量，整数
7. 页面层后续如只取部分点做展示，必须在消费层裁剪，不允许回退到 raw 聚合

---

## 5. 手动物化命令冻结

### 5.1 首期触发方式

1. 仅支持手动命令
2. 不支持自动触发
3. 不接入调度器

### 5.2 命令语义

命令名本轮可实现时再定，但语义必须冻结为：

1. 指定 `trade_date`
2. 指定 `type=stock`
3. 指定 `market=CN_A`
4. 默认物化全部频率：`1/5/15/30/60`
5. 可选单频率重建

建议语义：

```text
goldenshare wealth-build-turnover-snapshot --trade-date YYYY-MM-DD
goldenshare wealth-build-turnover-snapshot --trade-date YYYY-MM-DD --freq 30
```

### 5.3 幂等规则

1. 同一 `(type, market, trade_date, freq)` 反复执行，结果必须覆盖同一主键行
2. 不允许累计叠加旧结果
3. 单频率重建不得影响其他频率快照

---

## 6. 页面读取链路冻结

### 6.1 `turnover` 模块读取规则

1. 最新可用交易日：从 snapshot 读取
2. 分钟曲线：从 snapshot 的 `points_json` 读取
3. 页面不得再查询 `raw_tushare.stk_mins` 生成图表
4. 页面不得因 snapshot 不存在而 fallback 到 raw

### 6.2 API 契约边界

1. `/api/v1/wealth/market/turnover` 路径保持不变
2. 顶层响应结构保持不变
3. 允许 `debugInfo` 增补模块内部观测，但不得破坏既有消费者

---

## 7. 读写切换范围冻结

本轮允许修改的实现点仅限：

1. 快照表模型 / Alembic 迁移
2. 快照物化器与手动命令
3. `turnover` 查询链路切到 snapshot
4. `turnover` debug 观测适配 snapshot 来源
5. 对应测试与文档

本轮禁止：

1. 修改 `turnover` 页面布局
2. 修改 `turnover` API 路径
3. 修改其他模块数据来源
4. 修改 TaskRun 模型
5. 修改通用审计模型
6. 引入自动触发/缓存/异步补偿

---

## 8. 消费者审计清单

编码前必须逐项审计：

1. `src/biz/queries/wealth/market/turnover/turnover_query.py`
2. `src/biz/queries/wealth/market/turnover/turnover_state_query.py`
3. `src/biz/queries/wealth/market/turnover/turnover_query_service.py`
4. `src/biz/services/wealth/market/turnover/turnover_status_resolver.py`
5. `src/biz/api/wealth/market/turnover.py`
6. `wealth/src/features/market-overview/turnover/api/marketTurnoverApi.ts`
7. `wealth/src/features/market-overview/turnover/api/marketTurnoverAdapter.ts`
8. `wealth/src/features/market-overview/turnover/TurnoverOverviewPanel.tsx`
9. `wealth/src/pages/market-overview/MarketOverviewPage.tsx`
10. `tests/web/test_wealth_market_turnover_api.py`
11. `wealth/src/pages/market-overview/MarketOverviewPage.test.tsx`

要求：

1. 旧 raw 在线聚合路径必须清零
2. 不允许页面层偷偷拼 `points_json`
3. 不允许查询层保留“snapshot 没有就 fallback raw”的分支

---

## 9. 性能门禁

1. `/api/v1/wealth/market/turnover` P95 目标：`< 500ms`
2. 单次页面请求内不得出现 `raw_tushare.stk_mins` 全表或月分区聚合
3. “最新交易日探测”必须是 snapshot 级 O(1)/轻索引查询
4. 单日单频率曲线读取必须是单行快照读取，不允许临时分组聚合

---

## 10. 测试门禁

1. 单元测试：
   - `points_json` 生成顺序
   - `source_row_count/security_count` 计算
   - 单频率覆盖重建幂等
2. 集成测试：
   - 手动物化命令成功构建 `1/5/15/30/60`
   - 重跑同日同频率不产生重复行
   - `build_status=FAILED` 时 API 不读取失败快照
3. API 测试：
   - `turnover` 真实接口改读 snapshot 后结构不变
   - `debugInfo` 能看到 snapshot 观测日期
4. 前端 smoke：
   - 页面模块正常展示
   - snapshot 缺失时显示 error/loading 既有四态，不展示 mock 回填

---

## 11. 回滚策略冻结

1. 若物化器失败：
   - 允许停止切换
   - 不允许页面 fallback raw
2. 若 API 切换后发现快照错误：
   - 回退代码到 snapshot 接入前版本
   - 保留快照表与物化命令，不删除已建结构
3. 回滚动作必须只影响 `turnover` 模块，不波及其他模块

---

## 12. 签字清单

### 12.1 后端负责人

1. [ ] 快照表结构可实现
2. [ ] 手动物化链路可实现
3. [ ] raw 在线聚合路径清零方案明确

### 12.2 前端负责人

1. [ ] API 契约不破坏现有消费
2. [ ] 既有四态表达继续可用
3. [ ] debug 面板可复用 snapshot 观测

### 12.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 长期方案解决根因，不是 5 秒补丁
3. [ ] 可进入编码阶段

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-09 | 首版：冻结 turnover 分钟线快照长期改造的编码前门禁 | Codex |
