# 市场总览｜板块速览 M2 编码前门禁 v2

> 状态：按批准顺序实施中；Slice 5 本地代码与测试已完成，生产 PLAN/APPLY 仍按两阶段门禁执行。
> 规则：未勾选门禁不得越级进入对应后续阶段；本地代码完成不等于生产迁移、数据发布或上线验收通过。

关联文档：

1. [板块速览标杆需求 v2](./sector-overview-benchmark-requirement-v2.md)
2. [板块速览技术实施方案 v2](./sector-overview-implementation-design-v2.md)
3. [板块速览低层设计 v2](./sector-overview-low-level-design-v2.md)

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

1. [x] `silver_dc_industry_hierarchy` 与 prod read-back 均为 496 行及 31/128/337，canonical hash 一致。
2. [x] 生产只读审计确认 `dc_index.idx_type` 真实枚举。
3. [x] 生产只读审计确认 `dc_daily.category` 真实枚举。
4. [x] 生产只读审计确认 `board_moneyflow_dc.content_type` 真实枚举。
5. [x] `board_moneyflow_dc.ts_code` 非空率及与板块代码匹配率已记录，确认不使用名称模糊 join。
6. [x] 当前审计已确认：`dc_daily/dc_member` 以源站现状为口径，`board_moneyflow_dc@2026-07-09` 已补齐；这些单点事实不等于 60 日整窗验收。
7. [x] `dc_member` 在冻结 85 日窗口内逐日 pair 数为 31,717-71,132，单板最大成员数 3,850；主键约束与逐日板块覆盖核验无重复/缺板。
8. [x] `equity_daily_bar` 对原始成员集合的行情覆盖率已记录；该结果不等于有效池覆盖率。
9. [x] `equity_limit_list` 零行与“数据集已完成”状态区分方案已验证；首发 85 日窗口每日实际有 29-152 只涨停，不存在需完成证据解释的零行日。
10. [x] 特征 20 日/5 日窗口及复算所需 `dc_daily[t-25..t]`、`moneyflow[t-9..t]`、成员/股票事实 `[t-5..t]` 已用 SSE 开放日冻结，不用自然日替代。
11. [ ] 领涨股逐字段来自 `dc_index`，缺失时不设替代来源。
12. [x] `security_serving` 的 `security_type/curr_type/list_status/list_date/delist_date` 已按每个目标日投影资格；5,884 行均满足当前 EQUITY/CNY/L|D 形态且 `list_date` 非空。
13. [x] `equity_suspend_d` 的 `suspend_type='S'` 每日 1-57 行，首发窗口无零行日，`(trade_date, ts_code, suspend_type)` 重复为 0。
14. [x] 冻结窗口内每个概念的原始成员、有效 A 股、停牌、可报价、有效行情和真实缺行情均完成关系复算；真实缺行情恒为 0，`BK0636.DC/B股` 无有效 A 股并归为 `INVALID`。
15. [x] 全部必需 prod 来源的 60+25 日逐日枚举、日期、数量、唯一键、零行语义和资金流代码覆盖率台账已冻结；资金流对目标概念覆盖率 100%。
16. [x] CN_A 首发窗口已冻结为 60 个连续 SSE 开放日 `2026-05-20..2026-08-12`，warm-up 为 `2026-04-10..2026-05-19`；日期级缺口为 0。Prod Raw/Core 一致的单概念行情缺行按 `INVALID`，不跳日、不用窗外日期凑数。

### 1.3 数据库、连接与执行链

1. [x] 本需求 revision 创建时已确认本地与生产单 head `20260812_000133`，并正确接为 `20260813_000134`；部署后再次只读验收，仓库与生产当前单 head 已推进为 `20260813_000135`。后续迁移必须接当前真实 head。
2. [x] 两张新表字段、主键、索引、约束和 downgrade 已实现并通过模型、约束及迁移范围测试。
3. [x] 层级全表 `DELETE + INSERT + read-back` 单事务发布已实现并完成正式生产发布；496/31/128/337、闭包、版本及 source/prod hash 一致。
4. [x] 连接复用口径已确认：Web/Heat 使用现有 `DATABASE_URL`，DG hierarchy 使用现有 `ProdPostgresWriteResource` / `PROD_POSTGRES_WRITE_*` 和 `lake_raw_writer`；不新增账号、DSN、engine 或板块专用数据库配置。
5. [ ] 组件访问边界已评审：DG 只写 hierarchy，Heat 只写 Heat 且来源查询只读，Web 不产生 DML，运行时代码无 DDL/`TRUNCATE`；Heat/Ops 使用独立 Session/事务。
6. [x] Heat 来源查询全部只读 prod，并按交易日、概念和成员集合有界；禁止 Parquet、DuckDB、DG resource、Tushare 和 N+1。
7. [x] biz Heat quality contract 与按交易日 `DELETE + INSERT + read-back` 单事务发布已实现并通过回滚/read-back/幂等测试。
8. [x] ops generic executor port、TaskRun 节点/issue/checkpoint、app 注入与生产 CLI `ops-worker-run/serve` factory 消费已实现；静态依赖确认 `ops` 不 import `biz`，CLI 不直构未装配 worker。
9. [x] Heat business session 与 TaskRun ops session 独立并复用现有 Session factory；PostgreSQL 业务事务使用 `REPEATABLE READ`，本地测试确认 Ops 回滚不影响已提交 Heat。
10. [x] 60 个有效交易日从旧到新 PLAN/APPLY、首错停止、snapshot integrity、hash 漂移和已成功日期无 DML 续跑方案已实现并通过本地测试。
11. [x] DG 只保留 hierarchy 发布；静态清单确认不存在 DG Heat asset、dynamic partition、asset check、sensor、Gold、runless event 或 history CLI，hierarchy publisher 也未接 job/sensor/check/bootstrap 自动入口。
12. [x] 方案与 Heat 执行链代码均不包含 Kopia，静态门禁已覆盖。
13. [x] 本模块不新增数据库配置项；现有 `DATABASE_URL` 与 `PROD_POSTGRES_WRITE_*` 的消费者已经核对，URL/password 继续遵守通用日志脱敏规则。
14. [x] revision `20260813_000134` 已随部署应用；生产只读权限探针确认既有 `lake_raw_writer` 仅具备 `core_serving.wealth_sector_hierarchy` 的 `SELECT/INSERT/DELETE`，没有 `UPDATE/TRUNCATE`，且未创建 login 或新增连接配置。

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
9. [ ] 不读取 DG/Lake/Tushare 计算或回放 Heat，不生成 Gold/Parquet 第二份 Heat 事实。
10. [ ] 不把子特征权重、窗口、TopN、winsor 或质量阈值留成未进入配置 hash 的散落代码常量。

---

## 5. 数据质量判定矩阵

| 场景 | Heat 行 | API 状态 | 异常码 |
|---|---|---|---|
| 全部必需 prod 来源同日、证券资格可用、成员与历史完整 | 正常 | `READY` | 无 |
| 必需来源整日缺失，或物理零行且无完成证据 | 不发布该日 | `DELAYED/ERROR` | `SO_SOURCE_DELAYED/SO_QUERY_FAILED` |
| `dc_daily` 等源站现状仅缺单个概念的必需特征 | 保留该概念 `INVALID`，其它概念正常计算 | `PARTIAL` | `SO_HEAT_NOT_READY` |
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

### 6.1 hierarchy、Heat contract、访问边界与执行链

1. [x] 层级固定 schema、唯一键、31/128/337 和父子/根/路径/叶节点闭包已由 source loader 与纯 contract 测试覆盖。
2. [x] 层级 transaction rollback、版本和 canonical read-back hash 已由写入失败及回读篡改负例覆盖；正式生产 read-back 已通过。
3. [ ] 策略配置中心注册、canonical hash、非法权重、阈值、覆盖率、未知版本和版本未升负例。
4. [x] winsor 边界、平均秩、未舍入分排序和 `sector_code` 同分稳定排序已测试。
5. [x] 五分量、总分、最终两位小数、rank、level 与质量状态 golden test 已通过。
6. [x] `heatDelta1d`、原始趋势和两日趋势确认已覆盖固定样本。
7. [x] no-lookahead：未来输入变化不影响过去交易日结果。
8. [ ] 缺历史、缺资金、低覆盖、来源错日均失败或无效，不补权。
9. [x] 无效概念保留 `INVALID + reason`，不落成 0 分。
10. [x] prod 单日事务 `DELETE + INSERT + read-back` 与相同 config/source/content hash 幂等续跑已测试。
11. [x] plan/content drift 或 read-back 失败会回滚本日事务，并保留此前成功行。
12. [x] 有效池逐行资格边界、B 股排除、未上市/已退市排除、停牌保留、可报价分母和真实缺行情 golden test 已覆盖。
13. [ ] `quoteEligibleCount=0`、停牌源缺失、证券资格缺失和真实行情缺失负例。
14. [x] prod 来源 bundle 按 SSE 开放日冻结窗口有界读取；成员集合关系约束与 DG/Lake/Tushare/来源 DML 静态负例已覆盖。
15. [ ] 访问边界正例通过；DG 写 Heat、Heat 写来源/hierarchy、Web 产生 DML、运行时代码执行 schema DDL 或 `TRUNCATE` 的负例均被测试阻止。
16. [x] ops executor port 经 app adapter 调用 biz；静态/依赖测试确认 ops 不 import biz，未装配时失败关闭。
17. [x] Heat business session 与 TaskRun session 隔离；状态事务回滚不回滚已提交 Heat。
18. [x] 60 个有效交易日从旧到新、首错停止、plan/content hash 与断点幂等续跑已测试；缺口后继日标记 `PREDECESSOR_GAP`。
19. [x] 仓库静态扫描确认不存在 DG Heat asset/partition/check/sensor/Gold/runless event/history CLI。
20. [x] `ops-worker-run/serve` 经 app factory 注入 Heat executor；默认未装配 worker 对 Heat action 失败关闭，既有非 Heat action回归通过。
21. [ ] Web/Heat 使用现有应用连接、DG 使用现有 prod write resource 的装配测试通过；现有 URL/password 不进入日志、TaskRun 或异常文本。
22. [x] replay PLAN 只保存 snapshot/gap ledger、不写 Heat；APPLY 必须引用同 action 成功 PLAN 的 `plan_task_run_id + plan_hash`，校验日期窗与 snapshot integrity，逐日 plan/content 漂移在 DML 前停止。
23. [x] replay 与单日 action 当前均不可调度；只经既有 Ops TaskRun/worker 执行，不新增 sensor/隐藏 cron。
24. [x] app completion-evidence provider 只把成功的点式来源 TaskRun 映射为中立 DTO；biz 不 import ops，合法零行 evidence id/hash 纳入 source hash，缺证据阻断已测试。

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

### 6.4 固定执行命令与通过标准

```bash
pytest -q \
  tests/test_extended_models.py \
  tests/test_foundation_table_model_registry.py \
  tests/test_wealth_sector_serving_constraints.py \
  tests/test_wealth_sector_serving_migration.py \
  tests/test_wealth_sector_heat_contract.py \
  tests/test_wealth_sector_heat_materialization.py \
  tests/test_wealth_sector_heat_replay_planner.py \
  tests/test_sector_heat_task_executor.py \
  tests/web/test_wealth_sector_heat_ops_runtime.py \
  tests/web/test_ops_manual_actions_api.py \
  tests/architecture/test_wealth_sector_heat_guardrails.py \
  tests/test_cli_ops_runtime.py \
  tests/web/test_wealth_market_sector_overview_api.py \
  tests/architecture/test_subsystem_dependency_matrix.py

cd wealth
npm run test -- market-overview-sector-overview-real-api
npm run typecheck
npm run build

cd ../lake_console/orchestrator
uv run python -m pytest -q tests/test_wealth_sector_hierarchy_prod_core.py
uv run ruff check src/orchestrator/defs tests/test_wealth_sector_hierarchy_prod_core.py

cd ../..
.venv/bin/python scripts/check_docs_integrity.py
git diff --check
```

通过标准：全部命令零失败；后端走真实路由，前端禁用 mock fallback；用户可见核心字段、状态过程和异常文案均有断言。`uv run dg check defs` 只验证 hierarchy Definitions 加载并按 DG 运维门禁单独记录，不得扩展成 Heat job/sensor/materialize/backfill 或数据写入；静态门禁必须同时证明没有 Heat DG 定义。

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
| 60 个有效交易日回放平均/日 | `<60s` |  |  |
| 层级 read-back | `496` |  |  |
| Heat read-back | `candidate rows = prod rows` 且 canonical hash 一致 |  |  |

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

1. [ ] 实施日真实 Alembic head 已确认；两表迁移、现有连接复用、`lake_raw_writer` hierarchy 单表授权、组件访问边界和双 Session 事务测试完成。
2. [x] DG hierarchy -> prod hierarchy 发布、496/31/128/337 与 hash read-back 完成。
3. [x] 60+25 日生产来源台账已冻结；日期级缺口清零，Prod Raw/Core 一致的局部源站缺行已冻结为逐概念 `INVALID` 证据。
4. [ ] prod-native Heat 60 个有效交易日 TaskRun 回放、read-back、重放一致性和性能验收完成。
5. [ ] 最新交易日 Heat 发布和来源日期对账完成。
6. [ ] 只读 prod 的后端 V2 完成并通过真实 API 验收。
7. [ ] 前端三工作台在同一发布窗口切换，随后完成首页 smoke、截图和性能验收。
8. [ ] 监控 `SO_*`、P95、Heat 覆盖、Ops TaskRun 和 DG hierarchy 发布状态。

### 9.2 回滚

1. 应用回滚到切换前版本，V2 新表保留以供诊断。
2. 不删除或清空任何来源业务表。
3. 不临时恢复字段别名或双 DTO。
4. Heat 发布失败只回滚该交易日业务事务；来源数据不受影响，TaskRun 状态事务也不得反向影响业务事务。

---

## 10. 通用清单映射矩阵

对应 [wealth 模块交付通用清单 v1](../../system/module-delivery-checklist-v1.md)。“不适用”均给出本模块语义理由，不视为默认继承。

| 通用条目 | 结论 | 本模块落点/理由 | 验收证据 |
|---|---|---|---|
| 2.1 三件套先行 | 适用 | benchmark / implementation / coding gate 已存在，LLD 补充编码级落点 | 本文件签字前仍禁止编码 |
| 2.2 后端事实归一 | 适用 | 后端产出层级、候选、排序、选择、Heat、leader、有效池计数；前端只展示 | 真实 API 字段断言 + adapter 无事实计算测试 |
| 2.3 模块状态机 | 适用 | `loading/ready/partial/delayed/empty/error/forbidden` 共用骨架，5 秒超时 | 前端状态过程测试 |
| 2.4 显示与数据语义绑定 | 适用 | `direction/heatLevel/heatTrend/heatStatus` 结构化驱动颜色与标签 | 正负/null/INVALID 可见断言 |
| 2.5 行为过程测试 | 适用 | 覆盖首次加载、刷新、超时、重试、Tab/排名/三级联动和 stale response | frontend real-api tests |
| 2.6 文档实现同轮同步 | 适用 | V2 四份文档、API 基线、异常码、测试必须随实现同轮更新 | 提交 diff 清单 |
| 2.7 模块级渐进替换 | 适用 | 只替换 sectorOverview；`sectors` source 保持 real 并记录前后值；无 mock fallback | source 配置断言 + 首页 smoke |
| 2.8 契约先行 | 适用 | 本文件第 2/3 节与 LLD 第 6/7 节冻结请求、响应和消费者 | 后端 schema + TS contract test |
| 2.9 图表坐标与说明 | 适用 | 仅概念 Heat 历史小图，业务域固定 `0..100`；不常驻解释轴文案 | 渲染域断言 + 截图 |
| 2.10 统计与传输边界 | 适用 | biz 使用 prod 有界 SQL + 纯 contract 盘后物化；API 只读 serving；P95 `<250ms`、5 秒前端超时 | 来源 SQL/物化/API benchmark |
| 2.11 配置生效语义 | 适用 | 本模块只新增 Heat JSON 策略配置；数据库复用现有 `DATABASE_URL` 与 `PROD_POSTGRES_WRITE_*`，不新增板块专用配置，策略参数变化必须升版本 | config schema、现有连接复用、secret 脱敏与非法配置正反测试 |
| 2.12 通用映射矩阵 | 适用 | 即本节 | 评审签字 |
| 2.13 例外白名单与语义断言 | 适用 | 本模块当前无例外；Heat 域和状态语义必须可执行断言 | 第 11 节 + chart/status tests |
| 2.14 图表参数优先级 | 适用 | Heat 历史组件显式 `yMin=0/yMax=100` 时渲染层不得二次改写 | chart prop/render test |
| 2.15 双图坐标区对齐 | 不适用 | 本模块没有并排且共用坐标语义的双图；三级列表不是图表 | 组件树审查确认无双图 |
| 2.16 卡片文案单行 | 适用 | 板块名、核心指标、领涨股独立容器，名称/股票名单行省略 + tooltip | 长名称 smoke + 截图 |
| 2.17 真实 API 双门禁 | 适用 | 后端走真实路由；前端禁用 mock adapter 验证用户可见字段 | 指定真实 API 测试命令与结果 |
| 2.18 跨模块抽象原则 | 适用 | 逐条映射见下表 | 原则 1..8 均有代码与测试落点 |

### 10.1 跨模块八原则映射

| 原则 | 代码落点 | 测试/门禁 |
|---|---|---|
| 1 事实源单一 | Heat/行情/成员/资金全部来自 prod；DG 只发布 hierarchy；后端 DTO 与 adapter 不补事实 | 禁止 DG Heat/Lake adapter、leader 来源、null 不补 0、旧字段清零 |
| 2 契约先行冻结 | V2 schema + TS 判别式 workspace | 三视图真实 API contract |
| 3 配置一致性 | `sector_overview.cn_a.v1.json` 通过 `StrategyConfigService` 唯一供 biz Heat contract 使用 | registry/schema、config canonical hash 与非法配置负例 |
| 4 默认行为显式 | 默认 Tab/rank/selection、显式日期、Heat 未就绪、403 均已定义 | 默认与不回退测试 |
| 5 排序筛选确定 | 固定主排序、`NULLS LAST`、`sectorCode ASC`；生产枚举精确过滤 | 同分、空值、31 地域、Top5/Top20 |
| 6 性能预算前置 | prod serving 预计算、SQL 往返 `<=8`、API/物化预算 | 同机房 API 与 60 个有效交易日回放记录 |
| 7 可观测异常标准化 | `SO_*` registry + structured debug；Ops TaskRun reason/source/config/content hash | 每个异常码、CLI factory、TaskRun 失败/续跑和 debug 分层测试 |
| 8 用户可见结果测试 | 名称、主指标、leader、Heat、成员、层级/地域均为主断言 | 后端真实路由 + 前端真实 API 双门禁 |

---

## 11. 模块例外白名单

当前例外白名单：**无**。

1. 第 10 节标为“不适用”的双图规则，是因为本模块不存在对应 UI 结构，不构成偏离规则。
2. 如实现阶段需要放宽 Heat `0..100` 坐标域、用前端计算 Heat 标签、允许 mock fallback、放宽来源同日或其它硬口径，必须先新增例外条目并回到产品/技术评审；不得直接编码。

---

## 12. 签字

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

## 13. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v2.8 | 2026-08-13 | 记录 Slice 5 本地门禁：Heat 配置/公式/来源/有效池/事务、REPEATABLE READ、60 日 PLAN/APPLY、snapshot integrity、断点续跑、Ops/app/CLI、完成性证据和静态访问边界已实现测试；生产回放保持未执行 |
| v2.7 | 2026-08-13 | 记录 hierarchy 正式发布、60+25 日九张 prod 来源审计和有效池验收；将日期级缺口与源站局部概念缺行分开，后者冻结为 `INVALID` 而非整日阻断 |
| v2.6 | 2026-08-13 | 记录生产当前单 head `20260813_000135`、两表与 hierarchy 授权验收通过，以及 Slice 3 hierarchy publisher 和 DG Heat/自动入口清零测试已实施；正式生产 hierarchy 发布仍待部署后单独执行 |
| v2.5 | 2026-08-13 | 记录 Slice 1/2 实施：基于已复核的 head `20260812_000133` 完成两表 ORM/注册、revision `20260813_000134` 及本地正反测试；本提交 head 为 `000134`，生产仍为 `000133`、尚未迁移 |
| v2.4 | 2026-08-13 | 撤回三账号/三 DSN 门禁；Web/Heat 复用现有应用连接，DG 复用现有 prod write resource；改为组件访问边界、Heat/Ops 双 Session 事务和既有 `lake_raw_writer` hierarchy 单表授权门禁 |
| v2.3 | 2026-08-13 | Heat 改为 biz prod-native 计算、ops 执行意图/状态/观测、app 注入；删除 DG Heat/Gold 双份事实，增加 60 个有效交易日门禁；三账号/三 DSN 门禁已由 v2.4 撤回 |
| v2.2 | 2026-08-12 | 增加 LLD 入口、通用清单逐项映射、跨模块八原则映射与“无例外”白名单 |
| v2.1 | 2026-08-12 | 增加地域第三视图；冻结有效 A 股成分池、停牌感知可报价池和对应测试门禁 |
| v2 | 2026-08-12 | 冻结行业三级联动、概念盘后热度、V2 API、数据链和发布门禁 |
