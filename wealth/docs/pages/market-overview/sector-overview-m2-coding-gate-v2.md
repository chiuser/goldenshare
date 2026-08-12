# 市场总览｜板块速览 M2 编码前门禁 v2

> 状态：待产品、设计、数据与技术共同评审。
> 规则：本清单未签字前，不允许开始 V2 业务编码、迁移或生产物化。

关联文档：

1. [板块速览标杆需求 v2](./sector-overview-benchmark-requirement-v2.md)
2. [板块速览技术实施方案 v2](./sector-overview-implementation-design-v2.md)

---

## 1. 总门禁

### 1.1 产品与设计

1. [x] 首页盘后定位确认：本期不使用实时行情、分钟数据或 Redis 热度事实。
2. [x] Figma `heat_delta_20m` 已改为 `heat_delta_1d`。
3. [x] Figma “日内加速度/分钟新鲜度/分钟刷新”已改为日度口径。
4. [x] 行业三列各 Top5、概念 Top20、地域全部 31 个返回与两类平铺榜单 7 行可视已冻结。
5. [x] 行业三种、概念四种和地域三种排名维度已冻结。
6. [x] 领涨股、成员 Top5、地域涨跌分布、热度等级和趋势文案已冻结。
7. [x] 概念详情最近 20 个交易日热度历史及断点规则已冻结。
8. [x] Figma 行业/概念/地域 `1564 × 680` 基线截图已归档；正式节点为 `538:520/538:521/571:516`。
9. [x] 有效 A 股池、B 股/未上市排除、停牌单列和可报价池覆盖率文案已进入正式 Figma。

### 1.2 数据与来源

1. [ ] `silver_dc_industry_hierarchy` 496 行及 31/128/337 分布复核通过。
2. [x] 生产只读审计确认 `dc_index.idx_type` 真实枚举。
3. [x] 生产只读审计确认 `dc_daily.category` 真实枚举。
4. [x] 生产只读审计确认 `board_moneyflow_dc.content_type` 真实枚举。
5. [x] `board_moneyflow_dc.ts_code` 非空率及与板块代码匹配率已记录，确认不使用名称模糊 join。
6. [x] 六类既有盘后来源目标日、行数、唯一键和样本已对账。
7. [ ] `dc_member` 当日 pair 数、单板最大成员数与重复率已记录。
8. [x] `equity_daily_bar` 对原始成员集合的行情覆盖率已记录；该结果不等于有效池覆盖率。
9. [ ] `equity_limit_list` 零行与“数据集已完成”状态区分方案已验证。
10. [ ] 特征 20 日/5 日窗口及复算所需 25/10/5 日有界来源窗口均使用已完成交易日，不用自然日替代。
11. [ ] 领涨股逐字段来自 `dc_index`，缺失时不设替代来源。
12. [ ] `security_serving` 的 `security_type/curr_type/list_status/list_date/delist_date` 完整率与目标日资格分类已对账。
13. [ ] `equity_suspend_d` 目标日完成证据、`suspend_type='S'` 数量及零行语义已验证。
14. [ ] 每个概念的原始成员、有效 A 股、B 股、未上市、已退市、停牌、可报价、有效行情和真实缺行情数量可逐项复算。

### 1.3 数据库与 DG

1. [ ] 实施当日重新检查 Alembic head。
2. [ ] 两张新表字段、主键、索引、约束和 downgrade 已评审。
3. [ ] 层级全表事务替换与 read-back 方案已评审。
4. [ ] Heat Gold 路径位于正式 Lake Gold 层，staging 只使用 `/Volumes/datasource/data_lake_staging`。
5. [ ] Heat 来源查询全部按日期/成员集合有界。
6. [ ] Heat 七类 asset check 的阻断级别已冻结，新增 effective-pool check。
7. [ ] Heat serving 按交易日事务替换、hash/read-back 已冻结。
8. [ ] 60 日从旧到新回放、checkpoint 和续跑方案已冻结。
9. [ ] 来源表写入与 Heat 状态/发布事务完全隔离。
10. [ ] 方案与代码均不包含 Kopia。

### 1.4 API 与前端

1. [ ] 请求参数、默认值、互斥规则已冻结。
2. [ ] V2 响应样例通过前后端评审。
3. [ ] 默认三级选择路径与无子级行为已冻结。
4. [ ] 热度未就绪时不回退其它排序维度。
5. [ ] V1/V2 原子切换，不保留 DTO 别名或双契约。
6. [ ] 前端组件树、状态归属和 stale response 防护已评审。
7. [ ] Loading/Empty/Error/Partial/Delayed/Forbidden 共用稳定骨架。
8. [ ] 删除旧 `columns/heatMapItems` 的清单已确认。

### 1.5 测试与发布

1. [ ] Heat 固定样本 golden test 通过评审。
2. [ ] no-lookahead、缺源、不补权和来源错日负例已冻结。
3. [ ] 后端用户可见契约用例已冻结。
4. [ ] 前端真实 API 与交互用例已冻结。
5. [ ] API P95、payload、SQL 往返和离线物化预算已冻结。
6. [ ] 迁移、层级、Heat 回放、应用切换的发布顺序已冻结。
7. [ ] 应用回滚不依赖恢复旧 DTO 的方案已冻结。
8. [ ] 产品、设计、数据、后端、前端、运维签字完成。

---

## 2. 请求契约冻结

```ts
interface SectorOverviewRequestV2 {
  market?: "CN_A"; // default CN_A
  tradeDate?: string; // YYYY-MM-DD，盘后交易日
  view?: "INDUSTRY" | "CONCEPT" | "REGION"; // default INDUSTRY
  industryRankMetric?: "CHANGE_PCT" | "MAIN_NET_INFLOW" | "UP_COUNT";
  selectedIndustryCode?: string;
  conceptRankMetric?: "HEAT_SCORE" | "HEAT_DELTA_1D" | "CHANGE_PCT" | "MAIN_NET_INFLOW";
  selectedConceptCode?: string;
  regionRankMetric?: "CHANGE_PCT" | "MAIN_NET_INFLOW" | "UP_COUNT";
  selectedRegionCode?: string;
  debug?: 0 | 1;
}
```

拒绝项：

1. `view=INDUSTRY` 同时提交 concept/region 参数。
2. `view=CONCEPT` 同时提交 industry/region 参数。
3. `view=REGION` 同时提交 industry/concept 参数。
4. 非 `CN_A` 市场。
5. 非法日期或代码格式。
6. `level/parentCode/limit/weights/thresholds/scoreVersion`。

---

## 3. 响应契约冻结

### 3.1 行业最小正常样例

```json
{
  "sectorOverview": {
    "tradeDate": "2026-08-11",
    "status": "READY",
    "view": "INDUSTRY",
    "asOf": "2026-08-11T18:30:00+08:00",
    "industry": {
      "rankMetric": "CHANGE_PCT",
      "selection": {
        "level1Code": "BK0001",
        "level2Code": "BK0101",
        "level3Code": "BK0201",
        "detailSectorCode": "BK0201"
      },
      "columns": [
        {
          "level": 1,
          "parentSectorCode": null,
          "rows": [
            {
              "rank": 1,
              "sectorCode": "BK0001",
              "sectorName": "示例一级行业",
              "level": 1,
              "primaryMetric": {
                "value": 3.21,
                "displayText": "+3.21%",
                "direction": "UP"
              },
              "leader": {
                "stockCode": "000001.SZ",
                "stockName": "示例股票",
                "changePct": 9.98
              },
              "selected": true
            }
          ]
        },
        {"level": 2, "parentSectorCode": "BK0001", "rows": []},
        {"level": 3, "parentSectorCode": "BK0101", "rows": []}
      ],
      "detail": {
        "sectorCode": "BK0201",
        "sectorName": "示例三级行业",
        "sectorType": "INDUSTRY",
        "hierarchyPath": "示例一级 / 示例二级 / 示例三级",
        "metrics": {
          "changePct": 2.18,
          "upCount": 18,
          "downCount": 4,
          "sourceMemberCount": 23,
          "memberCount": 22,
          "suspendedCount": 1,
          "quoteEligibleCount": 21,
          "validQuoteCount": 21,
          "missingQuoteCount": 0,
          "mainNetInflow": 1280000000,
          "turnoverAmount": 8520000000,
          "quoteCoverage": 1.0
        },
        "heat": null,
        "leader": null,
        "members": []
      }
    }
  }
}
```

### 3.2 概念最小正常样例

```json
{
  "sectorOverview": {
    "tradeDate": "2026-08-11",
    "status": "READY",
    "view": "CONCEPT",
    "asOf": "2026-08-11T18:35:00+08:00",
    "concept": {
      "rankMetric": "HEAT_SCORE",
      "selectedConceptCode": "BK1184",
      "rows": [
        {
          "rank": 1,
          "sectorCode": "BK1184",
          "sectorName": "人形机器人",
          "primaryMetric": {
            "value": 92.4,
            "displayText": "92.4",
            "direction": "UP"
          },
          "leader": {
            "stockCode": "002031.SZ",
            "stockName": "巨轮智能",
            "changePct": 9.98
          },
          "heat": {
            "heatStatus": "VALID",
            "invalidReason": null,
            "heatScore": 92.4,
            "heatLevel": "BOILING",
            "heatDelta1d": 8.6,
            "heatTrend": "HEATING",
            "heatRank": 1,
            "scoreVersion": "concept-heat-eod-v1",
            "tradeDate": "2026-08-11",
            "calculatedAt": "2026-08-11T18:20:00+08:00"
          },
          "selected": true
        }
      ],
      "detail": null
    }
  }
}
```

### 3.3 地域最小正常样例

```json
{
  "sectorOverview": {
    "tradeDate": "2026-08-11",
    "status": "READY",
    "view": "REGION",
    "asOf": "2026-08-11T18:35:00+08:00",
    "region": {
      "rankMetric": "CHANGE_PCT",
      "selectedRegionCode": "BK0000",
      "rows": [
        {
          "rank": 1,
          "sectorCode": "BK0000",
          "sectorName": "示例地域板块",
          "primaryMetric": {"value": 3.42, "displayText": "+3.42%", "direction": "UP"},
          "leader": {"stockCode": "000001.SZ", "stockName": "示例股票", "changePct": 9.98},
          "selected": true
        }
      ],
      "detail": null
    }
  }
}
```

样例中的代码与数值只用于冻结结构，不作为生产验收数据。

---

## 4. Heat EOD 公式冻结

### 4.1 主权重

```text
价格强度 30%
板块广度 25%
资金流 25%
活跃度 10%
持续性 10%
```

### 4.2 子特征

1. 价格：当日涨跌幅、5 日相对强度、较前一日涨跌幅加速度。
2. 广度：上涨成员占比、涨停成员占比。
3. 资金：`net_amount_rate` 当日强度、5 日正流入比例与斜率。
4. 活跃：当日板块成交额 / 前 20 个已完成交易日中位数。
5. 持续：前 5 日基础热度 Top20 连续天数、前一日基础名次与当日基础名次差。

### 4.3 禁止行为

1. [ ] 不使用分钟行情或盘中估算。
2. [ ] 不用当前或前一日最终 rank 反算持久性；只使用前四维基础热度 rank。
3. [ ] 不使用未来日期输入。
4. [ ] 不对缺失分量重新分配权重。
5. [ ] 不在 API 请求时计算 Heat。
6. [ ] 不修改参数但沿用旧 `scoreVersion`。
7. [ ] 不按代码前缀识别 A/B 股，不以行情存在与否反推上市或停牌状态。
8. [ ] 不把停牌成员计入可报价池分母，也不把停牌伪装成真实缺行情。

---

## 5. 数据质量判定矩阵

| 场景 | Heat 行 | API 状态 | 异常码 |
|---|---|---|---|
| 七类日频源同日、证券资格可用、成员与历史完整 | 正常 | `READY` | 无 |
| 有效 A 股 `memberCount < 10` | 保留 `INVALID` 行，总分为空 | `PARTIAL` | `SO_MEMBER_COVERAGE_LOW` |
| `quoteEligibleCount = 0` | 保留 `INVALID` 行，总分为空 | `PARTIAL` | `SO_MEMBER_COVERAGE_LOW` |
| `quoteCoverage < 0.80` | 保留 `INVALID` 行，总分为空 | `PARTIAL` | `SO_MEMBER_COVERAGE_LOW` |
| B 股/未上市/已退市成员 | 排除并记录计数 | 不单独降级 | 无 |
| 当日停牌成员 | 保留有效资格、排除出可报价分母 | 不单独降级 | 无 |
| 可报价成员无有效行情 | 计入 `missingQuoteCount` | 达到阈值后 `PARTIAL` | `SO_MEMBER_COVERAGE_LOW` |
| Heat 目标日未发布 | 无 | `PARTIAL` | `SO_HEAT_NOT_READY` |
| Heat source date 与响应日不一致 | 不消费 | `PARTIAL/DELAYED` | `SO_HEAT_SOURCE_MISMATCH` |
| 层级表缺失/闭包非法 | 不影响 Heat | `ERROR`（行业） | `SO_HIERARCHY_UNAVAILABLE` |
| 基础板块源全部无数据 | 无 | `EMPTY` | `SO_SOURCE_EMPTY` |
| 最近完整日落后期望日 | 旧日数据标真实日期 | `DELAYED` | `SO_SOURCE_DELAYED` |
| SQL/服务失败 | 不确定 | `ERROR` | `SO_QUERY_FAILED` |

---

## 6. 必须存在的测试

### 6.1 DG 与存储

1. [ ] 层级固定 schema、唯一键、31/128/337 和父子闭包。
2. [ ] 层级 transaction rollback 与 read-back hash。
3. [ ] Heat 配置非法权重、阈值、覆盖率和版本负例。
4. [ ] winsor 边界、平均秩和同分稳定排序。
5. [ ] 五分量与总分 golden test。
6. [ ] `heatDelta1d` 和两日趋势确认。
7. [ ] no-lookahead：未来输入变化不影响过去分区。
8. [ ] 缺历史、缺资金、低覆盖、来源错日均失败或无效，不补权。
9. [ ] 无效概念保留 `INVALID + reason`，不落成 0 分。
10. [ ] Gold 原子提升和 serving 分区幂等重跑。
11. [ ] 发布失败保留上次成功分区。
12. [ ] 有效池逐行资格边界、B 股排除、未上市/已退市排除、停牌保留和可报价分母 golden test。
13. [ ] `quoteEligibleCount=0`、停牌源缺失、证券资格缺失和真实行情缺失负例。

### 6.2 后端

1. [ ] 一级只排一级、二级只排所选一级子级、三级只排所选二级子级。
2. [ ] 每列 Top5、概念 Top20 和地域全部 31 个候选。
3. [ ] 默认选择、合法选择保留、过期选择纠正、无子级。
4. [ ] 三种行业、四种概念、三种地域排名和空值排除。
5. [ ] 领涨股不从成员 Top1 推断。
6. [ ] 成员 Top5 严格按同日涨跌幅排序。
7. [ ] Heat 缺失不回退成 CHANGE_PCT。
8. [ ] 热度历史最多 20 点、日期升序、无效点不填充。
9. [ ] 响应只包含当前 view。
10. [ ] 地域固定使用生产枚举映射后的 31 个板块，不按股票 `area` 聚合，不返回层级或 Heat 字段。
11. [ ] V2 schema 不含 `columns/heatMapItems` 旧语义。
12. [ ] 每个状态和异常码分支。

### 6.3 前端

1. [ ] 三个 Tab 各自保留 rank 和 selection。
2. [ ] 三级点击联动与详情切换。
3. [ ] 概念和地域均为 7 行可视与内部滚动。
4. [ ] 快速切换不会被旧响应覆盖。
5. [ ] 名称、主指标、领涨股、Heat、成员股均有可见断言。
6. [ ] 长名称和缺失值不换行、不重叠。
7. [ ] 红涨绿跌、金额/百分比/Heat 格式正确。
8. [ ] 六态稳定骨架和模块级重试。
9. [ ] 无 mock fallback 冒充 ready。
10. [ ] 旧 8 列/20 格组件和 fixture 已清零。

---

## 7. 性能验收记录模板

| 项目 | 门槛 | 实测 | 结论 |
|---|---:|---:|---|
| API P50 | 记录 |  |  |
| API P95 | `<250ms` |  |  |
| API P99 | `<500ms` |  |  |
| payload | `<120KB` |  |  |
| SQL round trips | `<=8` |  |  |
| 单日 Heat P95 | `<60s` |  |  |
| 60 日回放平均/日 | `<60s` |  |  |
| 层级 read-back | `496` |  |  |
| Heat read-back | `gold rows = prod rows` |  |  |

必须分别记录本地测试、同机房生产只读/最小发布验收；本地结果不能替代生产结论。

---

## 8. 视觉验收记录模板

| 场景 | 基线 | 实现截图 | 最大偏差 | 结论 |
|---|---|---|---:|---|
| 行业 / 涨跌幅 | Figma `538:520` |  |  |  |
| 行业 / 主力净流入 | Figma `538:520` |  |  |  |
| 行业 / 上涨家数 | Figma `538:520` |  |  |  |
| 概念 / 综合热度 | Figma `538:521` |  |  |  |
| 概念 / 日度热度变化 | 修正版 Figma |  |  |  |
| 地域 / 涨跌幅 | Figma `571:516` |  |  |  |
| 地域 / 主力净流入 | Figma `571:516` |  |  |  |
| 地域 / 上涨家数 | Figma `571:516` |  |  |  |
| Partial | 状态骨架 |  |  |  |
| Empty/Error/Forbidden | 状态骨架 |  |  |  |
| 首页完整页 | `1600 × 1200` 首页 |  |  |  |

普通 UI 元素相对基线偏差不得超过 2px；不得新增换行、裁剪、重叠或溢出。

---

## 9. 发布与回滚门禁

### 9.1 发布顺序

1. [ ] 应用兼容新表但尚不切 API 的数据库迁移完成。
2. [ ] 层级 serving 发布和 496 行生产 read-back 完成。
3. [ ] Heat 60 日历史回放完成。
4. [ ] 最新交易日 Heat 发布和来源日期对账完成。
5. [ ] 后端 V2 与前端 V2 在同一发布窗口切换。
6. [ ] 真实 API、首页 smoke、截图和性能验收完成。
7. [ ] 监控 `SO_*`、P95、Heat 覆盖和 DG 物化状态。

### 9.2 回滚

1. 应用回滚到切换前版本，V2 新表保留以供诊断。
2. 不删除或清空任何来源业务表。
3. 不临时恢复字段别名或双 DTO。
4. Heat 发布失败只回滚该日 Heat 分区事务；来源数据不受影响。

---

## 10. 签字

| 角色 | 结论 | 姓名/日期 |
|---|---|---|
| 产品 |  |  |
| 设计 |  |  |
| 数据/DG |  |  |
| 后端 |  |  |
| 前端 |  |  |
| 运维 |  |  |

所有角色完成签字后，才允许将状态从“评审稿”改为“允许编码”。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v2.1 | 2026-08-12 | 增加地域第三视图；冻结有效 A 股成分池、停牌感知可报价池和对应测试门禁 |
| v2 | 2026-08-12 | 冻结行业三级联动、概念盘后热度、V2 API、数据链和发布门禁 |
