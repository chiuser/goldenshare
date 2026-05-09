# 市场总览｜市场风格技术实施方案 v1（implementation-design）

> 用途：把“市场风格”需求文档转成可实施技术方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

---

## 1. 文档目的

1. 对应需求文档：  
   [market-style-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-style-benchmark-requirement-v1.md)
2. 本文目标：冻结市场风格模块的数据源配置、查询编排、状态与异常语义。
3. 本文不做：不落业务代码，不改页面样式，不改其他模块。

关联门禁：  
[market-style-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-style-m2-coding-gate-v1.md)

---

## 2. 代码现状审计（必须基于真实代码）

1. `market-overview-baseline.md` 已冻结市场风格 UI 为 3 卡 + 三线图 + `1个月/3个月` 切换。
2. 当前页面级 API 文档对市场风格仍是“未专项重做”状态，尚未有独立模块三件套。
3. 策略配置中心已冻结为系统级基线：  
   [strategy-config-center-v1.md](/Users/congming/github/goldenshare/wealth/docs/system/strategy-config-center-v1.md)
4. 结论：
   - 市场风格模块必须直接接入统一策略配置中心；
   - 不允许模块内自读 JSON；
   - 先模块接口，再由 overview 聚合接入。

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：`GET /api/v1/wealth/market/style`
2. 是否整页聚合接口：否（模块接口）
3. 模块接口返回范围：仅 `style` 模块对象与必要状态字段

### 3.2 代码目录模板（按模块拆分）

```text
src/biz/
  api/
    wealth/
      market/
        style.py
  queries/
    wealth/
      market/
        style/
          style_query.py
          style_query_service.py
  schemas/
    wealth/
      market/
        style.py
  services/
    wealth/
      config/
        strategy_config_service.py
        strategy_config_registry.py
        strategy_config_models.py
        definitions/
          market_style.cn_a.v1.json
      market/
        style/
          style_status_resolver.py
          style_exception_builder.py
```

---

## 4. 数据流与执行链路

1. 请求入口：`api.wealth.market.style`
2. 参数校验：`market/tradeDate/debug`（`market` 首期仅 `CN_A`）
3. 配置装载：`strategy_config_service.get_payload(module_key="marketStyle", market="CN_A")`
4. 查询编排：
   - 指数链路：按配置 index code 查询大盘、小盘 `pct_chg`
   - 中位链路：按交易日在 `equity_daily_bar` 计算离散中位
   - 历史链路：按 `1个月(22)`、`3个月(62)` 交易日生成三线
5. 状态归并：`style_status_resolver`
6. 异常组装：`style_exception_builder`
7. 响应输出：`schemas.wealth.market.style`
8. 前端接入行为门禁（真实源）：
   - 请求 pending：页面该模块显示 `loading`；
   - 请求超过 5 秒：页面该模块显示 `error`；
   - `loading/error` 两种状态都禁止回填 mock 数据。

---

## 5. 查询编排策略

## 5.1 策略配置结构（冻结）

配置文件：`src/biz/services/wealth/config/definitions/market_style.cn_a.v1.json`

```json
{
  "moduleKey": "marketStyle",
  "market": "CN_A",
  "version": "1.0.0",
  "updatedAt": "2026-05-08T22:00:00+08:00",
  "updatedBy": "wealth-owner",
  "payload": {
    "ranges": {
      "oneMonthTradingDays": 22,
      "threeMonthTradingDays": 62
    },
    "cardSources": {
      "largeCap": {
        "sourceType": "index",
        "indexCode": "000300.SH",
        "label": "大盘股平均涨跌幅",
        "sourceText": "沪深300口径"
      },
      "smallCap": {
        "sourceType": "index",
        "indexCode": "000852.SH",
        "label": "小盘股平均涨跌幅",
        "sourceText": "中证1000口径"
      },
      "median": {
        "sourceType": "equity_median",
        "universe": "CN_A_ALL",
        "label": "涨跌中位数",
        "sourceText": "全市场样本"
      }
    }
  }
}
```

说明：

1. 三卡来源可配置，但卡片数量和顺序不可配置。
2. `median` 来源必须是 `equity_median`，禁止替换为插值中位。

## 5.2 主查询（当前日）

1. 大盘/小盘：
   - 来源：`core_serving.index_daily_serving`
   - 条件：`trade_date=:target_date and ts_code in (:large_code, :small_code)`
   - 输出：`pct_chg`
2. 涨跌中位数：
   - 来源：`core_serving.equity_daily_bar`
   - 条件：`trade_date=:target_date and pct_chg is not null`
   - 计算：`percentile_disc(0.5) within group (order by pct_chg)`

## 5.3 历史查询（1个月/3个月）

1. 先取交易日序列：
   - `trade_calendar` 最近 22/62 交易日
2. 指数历史：
   - `index_daily_serving` 按交易日序列 + 两个 index code 查询 `pct_chg`
3. 中位历史：
   - `equity_daily_bar` 按交易日分组计算离散中位
4. 合并输出：
   - 每个交易日一条 `MarketStyleHistoryPoint`
   - 字段：`tradeDate/largePct/smallPct/medianPct`

## 5.4 去重、排序、截断

1. 历史点按 `tradeDate` 升序输出。
2. 不做额外截断（由 22/62 交易日窗口控制）。
3. `tradeDate` 唯一键，重复行按最新查询结果覆盖。

## 5.5 空数据与异常数据处理

1. 单卡缺值：保留卡片，`valuePct=null`，方向 `UNKNOWN`。
2. 整模块全空：模块 `EMPTY`。
3. 配置非法：模块 `ERROR`，不做回退。

---

## 6. 状态与异常落地

1. `pageStatus`：沿用整页归并规则。
2. `moduleStatus`（debug）：
   - `moduleKey=marketStyle`
   - `expectedTradeDate/observedTradeDate/lagDays/status/note`
3. debug 输出：
   - 仅 `debug=1` 返回；
   - 生产环境禁用。
4. 异常码（需登记注册表）：
   - `ST_CONFIG_MISSING`
   - `ST_CONFIG_INVALID`
   - `ST_SOURCE_DELAYED`
   - `ST_SOURCE_EMPTY`
   - `ST_QUERY_FAILED`

---

## 7. 性能与缓存策略

1. 性能预算：P95 < 220ms（两指数 + 中位数 + 两档历史）。
2. 首版策略：无 Redis，仅依赖范围查询与分组聚合。
3. 二期缓存（可选）：
   - key：`wealth:style:{market}:{tradeDate}:{version}`
4. 一致性：
   - 配置变更后重启生效；
   - 数据更新按交易日自然覆盖。

---

## 8. 安全与权限

1. 鉴权依赖：沿用 `quote.read`。
2. 权限点：已登录且具备行情读取权限可访问。
3. 防误用策略：
   - 非法 market/date 直接 `400001`
   - debug 输出生产禁用。

---

## 9. 测试与验证计划

1. 单元测试：
   - 配置模型校验（3 卡来源字段完整）
   - 中位计算口径校验（离散中位）
2. 集成测试：
   - 正常/延迟/空/错误四态
   - `1个月/3个月` 历史点数量与排序
3. 冒烟验证：
   - 三卡值 + 三线图数据结构可直接消费
   - UI 不变
   - 真实源请求 pending 时显示 loading（不展示 mock style）
   - 真实源请求超过 5 秒显示 error（不回填 mock style）
4. 失败回滚与观测：
   - 配置异常时模块 ERROR 且有结构化异常
   - 不影响其它模块响应
5. 范围约束验证：
   - 本轮只允许 `marketStyle` 模块 source 从 `mock` 切到 `real`；
   - 其他模块 source 必须保持原值不变。

---

## 9.1 图表与说明文案约束（对齐 checklist）

1. 市场风格趋势值为百分比，可正可负；本模块不适用“纵轴从 0 起”的非负约束。
2. 若后续引入固定刻度，必须先在三件套文档写死刻度值，再落代码。
3. 图下“横轴/纵轴解释”等说明文案默认不常驻展示；仅在 benchmark 明确要求时允许展示。

---

## 10. 分期里程碑

1. M1（方案冻结）：三卡来源策略 + 中位口径 + API 契约冻结。
2. M2（后端实现）：style 模块接口、查询、状态、异常落地。
3. M3（前端接入）：接真实 style 模块数据，保持现有 UI 不变。
4. M4（回归发布）：联调、性能回归、灰度验收。

---

## 11. 风险与缓解

1. 风险：把中位数误实现为插值中位。  
   缓解：SQL 固定 `percentile_disc(0.5)` 并加单测锁死。
2. 风险：配置被改为非指数来源导致语义漂移。  
   缓解：payload 模型强约束 `large/small` 必须 `sourceType=index`。
3. 风险：历史数据某日缺值导致曲线断点。  
   缓解：允许点值为空但保留日期点位，前端按既有样式展示。

---

## 12. 已确认清零项

1. 三卡来源走统一策略配置中心。
2. 大盘默认 `000300.SH`，小盘默认 `000852.SH`，但可配置调整。
3. 中位数固定为离散中位（中间那只股票），不做插值。
4. UI 样式与交互保持不变。
5. 本轮无未决拍板项。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结市场风格模块实施口径（策略配置 + 离散中位） | Codex |
| v1.1 | 2026-05-09 | 对齐通用 checklist：补充真实源 loading/error 门禁、单模块切换约束与图表说明文案规则 | Codex |
