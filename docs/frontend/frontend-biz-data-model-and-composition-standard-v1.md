# 行情业务系统数据组织与页面编排规范 v1

## 1. 目标

定义前端如何组织数据，确保页面稳定、可测试、可演进。

核心原则：

1. 接口 DTO != 页面 ViewModel。
2. 页面只消费 ViewModel。
3. 映射逻辑单点收敛到 `entities`。

---

## 2. 分层数据流

```text
API DTO (shared/api)
  -> entities mapper
  -> Feature state model
  -> Widget props
  -> UI component render
```

约束：

1. `shared/api` 只关心请求和 DTO typing。
2. `entities` 负责语义转换和默认值兜底。
3. `features` 负责交互状态组合（筛选、分页、时间窗）。
4. `widgets` 只负责展示编排。

---

## 3. ViewModel 设计规则

每个页面级 ViewModel 必须包含：

1. `meta`: 数据时间、滞后信息、来源信息。
2. `content`: 页面主内容。
3. `status`: loading/empty/error/stale 状态提示信息。

示例结构：

```ts
interface QuotePageVM {
  meta: {
    ts_code: string;
    latest_trade_date: string | null;
    is_stale: boolean;
    stale_reason: string | null;
  };
  summary: {
    latest_price: number | null;
    change_amount: number | null;
    pct_chg: number | null;
    trend: 'rise' | 'fall' | 'flat';
  };
  chart: {
    period: 'day' | 'week' | 'month';
    bars: Array<{
      date: string;
      open: number;
      high: number;
      low: number;
      close: number;
      vol: number;
    }>;
  };
  status: {
    loading: boolean;
    empty: boolean;
    error_code: string | null;
    error_message: string | null;
  };
}
```

---

## 4. 页面编排规范

1. 一个页面一个 feature 入口，不跨页面共享临时 state。
2. 复杂图表区、榜单区、新闻区拆为独立 widget。
3. widget 接收纯 props，不自行请求接口。
4. 所有“字符串格式化/涨跌色判定/单位换算”统一走 entities 层。

---

## 5. 状态处理规范

必须覆盖四态：

1. `loading`: skeleton/占位
2. `empty`: 空态说明 + 下一步动作
3. `error`: 可读错误 + 重试
4. `stale`: 数据可能滞后提醒

禁止：

1. 页面内直接 `if (!data) return null` 隐性吞状态。
2. 把错误直接吐给用户（内部异常文本）。

---

## 6. 联调策略

1. 先接 page-init 和主数据接口。
2. 再接图表接口。
3. 最后接扩展信息接口（关联信息、公告、统计扩展）。

每个阶段都要确保：

1. 可单独渲染。
2. 错误可定位。
3. 状态可观测。

---

## 7. 测试建议

最小测试覆盖：

1. mapper 纯函数单测（DTO -> VM）。
2. feature 状态切换测试。
3. widget 渲染测试（含四态）。
4. 页面级 smoke（登录 + 页面打开 + 关键交互）。
