# 市场总览｜涨跌分布 M2 编码前门禁 v1

> 用途：在编码前冻结涨跌分布模块的参数、响应、查询、状态、异常与性能门禁。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [涨跌分布标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/breadth-benchmark-requirement-v1.md)
2. [涨跌分布技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/breadth-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`breadth`
2. 本门禁对应需求文档：`breadth-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`breadth-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 无配置化能力冻结
2. [ ] 请求与响应结构冻结
3. [ ] 核心样例响应冻结
4. [ ] 查询草案冻结
5. [ ] ClickHouse 只读连接/超时/测试替身方案冻结
6. [ ] 状态归并样例冻结
7. [ ] 异常覆盖矩阵冻结
8. [ ] 性能预算冻结
9. [ ] 前端真实源加载态门禁冻结（loading/ready/error）
10. [ ] 5 秒超时进入 error 且不展示 mock 回填的行为门禁冻结
11. [ ] 本轮仅 breadth 切换事实源、其余模块 source 不变
12. [ ] 平盘家数卡片副文案固定为“平盘率 x%”
13. [ ] 纵轴刻度固定为 0/1500/3000/4500/6000，且无负值刻度
14. [ ] API 与前端 DTO 均包含 `totalCount` 与完整 `distributionBuckets`
15. [ ] `distributionBuckets` 字段已升级为 `7~10` 与 `>10` 双分桶，不保留 `Gt7` 兼容字段
16. [ ] 前端右上角切换按钮固定为 `涨跌分布/涨跌家数`，默认激活 `涨跌分布`
17. [ ] `涨跌分布` 只渲染分桶柱状图本体，不展示底部汇总文字
18. [ ] `涨跌分布` 横轴标签不得展示 `涨` / `跌` 字样
19. [ ] `涨跌分布` 分桶数值必须贴近对应柱顶约 `10px`，不得固定排列在图表顶部
20. [ ] 本模块业务统计路径不得再聚合 `equity_daily_bar.pct_chg`
21. [ ] 签字完成

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface BreadthRequest {
  market?: "CN_A";    // default: CN_A
  tradeDate?: string; // YYYY-MM-DD
  debug?: 0 | 1;      // default: 0
}
```

参数校验规则：

1. `market` 非 `CN_A` -> `400001`
2. `tradeDate` 非法格式 -> `400001`
3. `debug` 非 `0/1` -> `400001`

### 3.2 响应结构冻结

```ts
interface BreadthDistributionBuckets {
  downGt10Count: number;
  down7To10Count: number;
  down5To7Count: number;
  down3To5Count: number;
  down0To3Count: number;
  up0To3Count: number;
  up3To5Count: number;
  up5To7Count: number;
  up7To10Count: number;
  upGt10Count: number;
}

interface BreadthMetrics {
  upCount: number;
  downCount: number;
  flatCount: number;
  totalCount: number;
  redRate: number;
  distributionBuckets: BreadthDistributionBuckets;
}

interface BreadthHistoryPoint extends BreadthMetrics {
  tradeDate: string;
}

interface BreadthResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  breadth: {
    tradeDate: string;
    metrics: BreadthMetrics;
    historyByRange: {
      "1m": BreadthHistoryPoint[]; // 22 points
      "3m": BreadthHistoryPoint[]; // 62 points
    };
  };
  debugInfo?: {
    modules: ModuleStatusItem[];
    exceptions: ModuleExceptionItem[];
  };
}
```

---

## 4. 核心样例响应（最小集合）

### 4.1 正常样例

```json
{
  "tradingDay": {
    "tradeDate": "2026-05-08",
    "prevTradeDate": "2026-05-07",
    "market": "CN_A",
    "isTradingDay": true,
    "sessionStatus": "CLOSED",
    "timezone": "Asia/Shanghai"
  },
  "pageStatus": { "status": "READY", "displayText": "数据已就绪" },
  "breadth": {
    "tradeDate": "2026-05-08",
    "metrics": {
      "upCount": 3421,
      "downCount": 1488,
      "flatCount": 219,
      "totalCount": 5128,
      "redRate": 66.71,
      "distributionBuckets": {
        "downGt10Count": 4,
        "down7To10Count": 8,
        "down5To7Count": 36,
        "down3To5Count": 184,
        "down0To3Count": 1256,
        "up0To3Count": 2860,
        "up3To5Count": 446,
        "up5To7Count": 86,
        "up7To10Count": 21,
        "upGt10Count": 8
      }
    },
    "historyByRange": {
      "1m": [
        {
          "tradeDate": "2026-04-10",
          "upCount": 2892,
          "downCount": 1983,
          "flatCount": 253,
          "totalCount": 5128,
          "redRate": 56.40,
          "distributionBuckets": {
            "downGt10Count": 3,
            "down7To10Count": 5,
            "down5To7Count": 41,
            "down3To5Count": 210,
            "down0To3Count": 1724,
            "up0To3Count": 2441,
            "up3To5Count": 360,
            "up5To7Count": 70,
            "up7To10Count": 15,
            "upGt10Count": 6
          }
        },
        {
          "tradeDate": "2026-05-08",
          "upCount": 3421,
          "downCount": 1488,
          "flatCount": 219,
          "totalCount": 5128,
          "redRate": 66.71,
          "distributionBuckets": {
            "downGt10Count": 4,
            "down7To10Count": 8,
            "down5To7Count": 36,
            "down3To5Count": 184,
            "down0To3Count": 1256,
            "up0To3Count": 2860,
            "up3To5Count": 446,
            "up5To7Count": 86,
            "up7To10Count": 21,
            "upGt10Count": 8
          }
        }
      ],
      "3m": []
    }
  }
}
```

### 4.2 delayed 样例

```json
{
  "pageStatus": { "status": "PARTIAL", "displayText": "部分模块数据延迟" },
  "debugInfo": {
    "modules": [
      {
        "moduleKey": "breadth",
        "expectedTradeDate": "2026-05-08",
        "observedTradeDate": "2026-05-07",
        "lagDays": 1,
        "status": "DELAYED",
        "note": "share_fact_market_breadth_daily lagged"
      }
    ],
    "exceptions": [
      { "module": "breadth", "code": "BR_SOURCE_DELAYED", "severity": "warn", "message": "source lagged" }
    ]
  }
}
```

### 4.3 empty 样例

```json
{
  "pageStatus": { "status": "EMPTY", "displayText": "暂无可用数据" },
  "breadth": {
    "tradeDate": "2026-05-08",
    "metrics": {
      "upCount": 0,
      "downCount": 0,
      "flatCount": 0,
      "totalCount": 0,
      "redRate": 0,
      "distributionBuckets": {
        "downGt10Count": 0,
        "down7To10Count": 0,
        "down5To7Count": 0,
        "down3To5Count": 0,
        "down0To3Count": 0,
        "up0To3Count": 0,
        "up3To5Count": 0,
        "up5To7Count": 0,
        "up7To10Count": 0,
        "upGt10Count": 0
      }
    },
    "historyByRange": { "1m": [], "3m": [] }
  }
}
```

### 4.4 error 样例

```json
{
  "pageStatus": { "status": "ERROR", "displayText": "请求失败，请稍后重试" },
  "debugInfo": {
    "exceptions": [
      { "module": "breadth", "code": "BR_QUERY_FAILED", "severity": "error", "message": "query failed" }
    ]
  }
}
```

---

## 5. 查询草案（可直接转实现）

1. 当日指标查询草案：
   - 从 `goldenshare_serving.share_fact_market_breadth_daily` 按 `trade_date = :target_date` 读取一行；
   - 直接读取 `up_count/down_count/flat_count/total_count/red_rate`；
   - 直接读取全部分桶列：`down_gt_10_count/down_7_10_count/down_5_7_count/down_3_5_count/down_0_3_count/up_0_3_count/up_3_5_count/up_5_7_count/up_7_10_count/up_gt_10_count`；
   - 禁止继续读取旧列 `down_gt_7_count/up_gt_7_count`；
   - 不再扫描或聚合 `equity_daily_bar.pct_chg`。
2. 历史趋势查询草案：
   - 先取最近 62 个交易日（`trade_calendar.is_open=true`）；
   - 再从事实表读取这些交易日对应行；
   - 结果按 `trade_date asc`；
   - `1m`=22 点、`3m`=62 点固定切片。
3. 状态查询草案：
   - `observedTradeDate` 来自事实表最新 `trade_date`（实现可用 `ORDER BY trade_date DESC LIMIT 1`，语义等同取最新观测日期）；
   - `expectedTradeDate` 仍来自交易日上下文。
4. 回退查询草案：
   - 不做跨日补值；
   - 不回退到旧 Postgres 个股日线聚合。
5. 重复行处理：
   - 每个 `trade_date` 期望单行；
   - 发现重复行应触发 `BR_FACT_DUPLICATED` 或查询失败，不允许静默合并。

---

## 5.1 ClickHouse 连接配置门禁

> 本节只约束 Web 后端连接 ClickHouse 的基础设施配置；breadth 模块仍然没有策略配置中心配置项。

| 配置名 | 默认值 | 来源 | 消费者 | 生效方式 | 门禁 |
|---|---|---|---|---|---|
| `WEALTH_CLICKHOUSE_URL` | `http://127.0.0.1:8123` | `Settings` / env | `ClickHouseReadonlyClient` | 重启生效 | 不得散落硬编码 |
| `WEALTH_CLICKHOUSE_DATABASE` | `goldenshare_serving` | `Settings` / env | `ClickHouseReadonlyClient` | 重启生效 | 查询走默认 database |
| `WEALTH_CLICKHOUSE_USER` | `default` | `Settings` / env | `ClickHouseReadonlyClient` | 重启生效 | 通过 HTTP 参数传递 |
| `WEALTH_CLICKHOUSE_PASSWORD` | 空字符串 | `Settings` / env | `ClickHouseReadonlyClient` | 重启生效 | 空值不传 password |
| `WEALTH_CLICKHOUSE_TIMEOUT_SECONDS` | `3` | `Settings` / env | `ClickHouseReadonlyClient` | 重启生效 | 同时用于 HTTP timeout 与 `max_execution_time` |

连接实现门禁：

1. client 必须只读，必须设置 timeout 与 ClickHouse 查询安全参数。
2. 查询失败统一转换为 `BR_QUERY_FAILED`，不得回退 Postgres 聚合。
3. API 测试必须通过 fake fact query 覆盖，不依赖真实 ClickHouse。

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` | 指标与历史完整 |
| `DELAYED` | `PARTIAL` | 数据日期落后 |
| `EMPTY` | `EMPTY` | 指标与历史均为空 |
| `ERROR` | `ERROR` / `PARTIAL` | 视整页其他模块归并 |

---

## 7. 异常码覆盖矩阵

> 异常码必须来自  
> `wealth/docs/system/exception-code-registry.md`

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `BR_SOURCE_EMPTY` | 空数据 | 目标日无事实行 | 模块 EMPTY |
| `BR_SOURCE_DELAYED` | 数据滞后 | observed < expected | 模块 DELAYED |
| `BR_HISTORY_INCOMPLETE` | 历史不足 | 历史点少于 22/62 | 模块 PARTIAL（debug 提示） |
| `BR_FACT_DUPLICATED` | 事实重复 | 单交易日多行 | 模块 ERROR |
| `BR_QUERY_FAILED` | 查询失败 | ClickHouse/服务异常 | 模块 ERROR |

---

## 8. 性能门禁

1. P95 预算：`< 200ms`
2. 返回体预算：`< 60KB`
3. 最大并发预算：按 overview 默认并发预算
4. 超预算降级策略：先优化事实表查询、连接复用与序列化，不引入复杂缓存

---

## 9. 测试门禁

1. 单元测试：
   - DTO 包含 `totalCount` 与完整 `distributionBuckets`；
   - DTO 和前端类型不包含 `downGt7Count/upGt7Count`；
   - DTO 和前端类型包含 `down7To10Count/up7To10Count/downGt10Count/upGt10Count`；
   - `1m/3m` 固定点数切片；
   - `涨跌家数` 模式只使用 up/down 折线；
   - `涨跌分布` 模式使用当日 `distributionBuckets + flatCount` 渲染柱状图；
   - 本模块查询层不再通过 `equity_daily_bar.pct_chg` 聚合业务指标。
2. 集成测试：
   - 正常/延迟/空/错误四态；
   - ClickHouse 查询失败进入模块 error；
   - 不回退旧聚合路径。
3. 冒烟测试：
   - 前端切换按钮文案与顺序为 `涨跌分布/涨跌家数`，默认激活 `涨跌分布`，不得继续显示 `1个月/3个月`；
   - `涨跌家数` 双趋势线（上涨/下跌）可渲染；
   - `涨跌分布` 分桶柱状图可渲染，且不展示底部汇总文字；
   - `涨跌分布` 横轴标签不得展示 `涨` / `跌` 字样；
   - `涨跌分布` 分桶数值必须贴近对应柱顶约 `10px`，不得固定排列在图表顶部；
   - 真实源请求 pending 时显示 loading（不展示 mock breadth）；
   - 真实源请求超过 5 秒显示 error；
   - 平盘家数卡片副文案显示 `平盘率 x%`；
   - 纵轴刻度固定 `0/1500/3000/4500/6000`，且不出现负值刻度。
4. debug 模式验证：
   - `debug=1` 返回明细；
   - 生产环境禁用 debug 输出。
5. 渐进替换约束验证：
   - 仅 `breadth` 事实源发生变化；
   - 非目标模块 source 与行为不变。

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] ClickHouse 只读 client/config/test double 可实现
2. [ ] 查询草案可实现
3. [ ] 状态归并无歧义
4. [ ] 异常覆盖完整

### 10.2 前端负责人

1. [ ] 响应结构可消费
2. [ ] 前端 DTO 可接收分桶字段
3. [ ] 右上角切换按钮文案与顺序为 `涨跌分布/涨跌家数`，默认激活 `涨跌分布`
4. [ ] `涨跌家数` 复用当前上涨/下跌双折线
5. [ ] `涨跌分布` 渲染分桶柱状图且不展示底部汇总文字
6. [ ] `涨跌分布` 横轴标签不展示 `涨` / `跌` 字样，分桶数值贴近柱顶约 `10px`
7. [ ] 空态/延迟态可表达

### 10.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 语义与当前页面一致
3. [ ] 分桶字段用于当前 `涨跌分布` 柱状图，且不引入额外底部汇总文字
4. [ ] 分桶展示不引入额外方向文字，涨跌方向由红绿柱和左右位置表达
5. [ ] 可进入编码阶段

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结涨跌分布模块编码门禁 | Codex |
| v1.1 | 2026-05-09 | 对齐模块交付清单：新增真实源加载态/5 秒超时门禁与单模块 source 渐进替换门禁 | Codex |
| v1.2 | 2026-05-09 | 对齐实现修复：新增平盘率副文案门禁与固定纵轴刻度门禁 | Codex |
| v1.3 | 2026-06-05 | 门禁切到 ClickHouse 事实表口径；新增分桶字段 DTO、旧聚合路径禁用与 ClickHouse 连接门禁 | Codex |
| v1.4 | 2026-06-06 | 对齐生产 fact 表新 schema：`Gt7` 退场，新增 `7To10/Gt10` 字段；补充 `涨跌分布/涨跌家数` UI 门禁，默认展示分桶柱状图 | Codex |
| v1.5 | 2026-06-07 | 分桶横轴标签去掉 `涨` / `跌` 字样；分桶数值改为贴近各自柱顶约 `10px` 展示 | Codex |
