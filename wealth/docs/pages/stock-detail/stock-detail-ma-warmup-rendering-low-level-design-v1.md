# 股票详情日线 MA 预热期绘制修正 LLD v1

> 状态：已实现并完成本地页面验收（2026-08-16）
> 范围：财势乾坤股票详情页日 K 的 `MA5/10/20/30/60/90/250`
> 目标：均线有效观测数不足时不绘制，不再用 `0` 冒充缺失值。

## 1. 冻结口径

1. `MA_N` 只有在该股票累计具备至少 `N` 个有效交易日收盘价后才有值。
2. 第 `1..N-1` 个有效交易日返回并保留 `NULL`；第 `N` 个有效交易日才出现第一条 `MA_N` 数值。
3. `NULL` 不得在后端、API adapter、ViewModel 或图表层转换成 `0`。
4. 缺失区间不绘制折线，不显示贴近 0 轴的横线，也不产生从 0 跳到首个有效值的竖线。
5. 主图顶部随十字光标变化的 MA 指标值，在缺失时显示 `--`，不显示 `0.00`。
6. 交易日计数以指标数据源的完整历史为准，不以当前 API 返回数组的下标或当前可视窗口为准。老股票即使接口只返回最近 300 根，首根返回数据仍可携带此前历史计算出的有效 `MA250`。

示例：

| 均线 | 不绘制区间 | 第一条可绘制位置 |
| --- | --- | --- |
| MA5 | 第 1～4 个有效交易日 | 第 5 个有效交易日 |
| MA10 | 第 1～9 个有效交易日 | 第 10 个有效交易日 |
| MA20 | 第 1～19 个有效交易日 | 第 20 个有效交易日 |
| MA30 | 第 1～29 个有效交易日 | 第 30 个有效交易日 |
| MA60 | 第 1～59 个有效交易日 | 第 60 个有效交易日 |
| MA90 | 第 1～89 个有效交易日 | 第 90 个有效交易日 |
| MA250 | 第 1～249 个有效交易日 | 第 250 个有效交易日 |

## 2. 当前代码事实与根因

当前日线链路为：

```text
core_serving.equity_factor_pro.ma_qfq_N
  -> StockDetailQuery
  -> stock_detail_field_mapper.to_float()
  -> StockMovingAverageDto: float | None
  -> StockKlineBarDto.factors.ma.maN: number | null
  -> stockDetailViewModelAdapter.toCandlePoint()
  -> StockCandlePoint
  -> DetailChartWorkspace / lightweight-charts
```

审计结论：

1. 后端查询直接读取预计算的 `ma_qfq_5/10/20/30/60/90/250`，不在页面查询中临时计算均线。
2. 后端 `to_float(None)` 返回 `None`，Pydantic DTO 和前端 API DTO 均已允许 MA 为 `NULL`。
3. 共享图表 `buildLineData(...)` 已将非有限值输出为 `{time}` 空白点，具备正确断线能力。
4. 真正的主链错误位于 `stockDetailViewModelAdapter.ts`：`valueOrZero(bar.factors.ma.maN)` 把合法 `NULL` 改成了 `0`。
5. `StockCandlePoint` 又把七个 MA 声明为非空 `number`，使错误转换成为类型要求。
6. `stockDetailMockAdapter.ts` 的 `movingAverage(...)` 会对不足 N 日的残缺窗口求平均，也不符合冻结口径。
7. 同仓指数详情已经采用 `finiteOrNull(...)`、可空 MA 类型和共享空白点绘制，是本次股票详情修正的直接实现基线。

因此，本次不重算生产指标、不改 SQL、不改 API 路径和响应结构；只修复股票详情消费链路对既有 `NULL` 语义的破坏，并补充合同测试。

## 3. 代码级修改

### 3.1 ViewModel 类型

修改：

`wealth/src/features/stock-detail/model/stockDetailTypes.ts`

将 `StockCandlePoint` 的以下字段由 `number` 改为 `number | null`：

```ts
ma5: number | null;
ma10: number | null;
ma20: number | null;
ma30: number | null;
ma60: number | null;
ma90: number | null;
ma250: number | null;
```

OHLC、成交量及其它本轮未涉及字段不借机改契约。

### 3.2 API Adapter

修改：

`wealth/src/features/stock-detail/api/stockDetailViewModelAdapter.ts`

新增与指数详情一致的有限数值转换：

```ts
function finiteOrNull(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
```

七个 MA 字段统一改为 `finiteOrNull(...)`。现有 `valueOrZero(...)` 继续服务本轮范围外的报价和基础行情字段，不做扩大重构。

禁止在 adapter 中按 `bar index + 1 >= N` 二次判断均线是否有效。原因是接口可只返回历史尾部，数组首根不等于股票上市首日。

### 3.3 图表与显示

涉及：

- `wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx`
- `wealth/src/shared/charts/detail-workspace/detailChartSeries.ts`

实现口径：

1. `toDetailChartPoint(...)` 原样把可空 MA 放入 `overlays`。
2. `stockFactor(...)` / `readStockFactor(...)` 继续返回 `number | null`。
3. 复用现有 `buildLineData(...)`：MA 为 `NULL` 时生成 `{time}` 空白点；不新增 0 值过滤，不删除对应 K 线时间轴。
4. `formatMetric(null)` 继续显示 `--`。主图顶部指标值和成交量面板中的 `MA5/MA10` 都遵循该规则。
5. 现有 K 线 Tooltip 不包含 MA 字段，本轮不新增 Tooltip 内容；十字光标移动时由顶部指标栏展示对应时点的 MA 或 `--`。
6. 不修改折线颜色、线宽、默认可视根数、缩放、左右拖动和十字光标同步行为。

共享 `buildLineData(...)` 当前语义已经正确，原则上不改实现，只保留其空白点回归测试。

### 3.4 Mock 数据

修改：

`wealth/src/features/stock-detail/api/stockDetailMockAdapter.ts`

`movingAverage(...)` 改为：

```ts
function movingAverage(closes: number[], index: number, size: number): number | null {
  if (index + 1 < size) return null;
  return round(average(closes.slice(index - size + 1, index + 1)));
}
```

Mock 当前复用 `ma30` 生成 BOLL。为避免本轮顺带改变 BOLL 业务语义，拆出仅供既有 BOLL mock 使用的 `partialMovingAverage(...)`；七条 MA 只允许调用上述严格 `movingAverage(...)`。本轮不修改 BOLL 的 ViewModel 类型和生产绘制合同。

### 3.5 后端合同保护

后端实现不需要修改。扩展：

`tests/web/test_wealth_stock_detail_api.py`

增加一个 MA 源字段为 `None` 的样本，断言 `/stock-detail/kline` 返回对应 JSON `null`，证明查询和 mapper 不会把缺失值改成 0。

## 4. 测试与验收

### 4.1 自动化测试

1. 新增 `stockDetailViewModelAdapter` 测试：API 的 `null/undefined` MA 保持 `null`，有限数值保持原值。
2. 扩展 `StockChartWorkspace.test.tsx`：
   - 前 4 根 `ma5=null`，第 5 根有值；对应 line data 前 4 根为 whitespace，第 5 根才有 `value`。
   - hover 前 4 根时显示 `MA5:--`，不得出现 `MA5:0.00`。
   - `ma250` 全部为空时不产生任何数值点。
3. 扩展 mock 测试：MA5/MA10/MA250 分别从第 5/10/250 根开始有值。
4. 保留共享图表现有测试：空值使用 whitespace，且不会被转换为 0。
5. 扩展后端 API 测试：数据库 `NULL` 必须原样输出为 JSON `null`。

建议验证命令：

```bash
cd /Users/congming/github/goldenshare
uv run pytest tests/web/test_wealth_stock_detail_api.py

cd /Users/congming/github/goldenshare/wealth
npm test -- \
  src/features/stock-detail/api/stockDetailViewModelAdapter.test.ts \
  src/features/stock-detail/chart/StockChartWorkspace.test.tsx \
  src/shared/charts/detail-workspace/DetailChartWorkspace.test.tsx
npm run typecheck
```

### 4.2 页面验收

至少验证两类股票：

1. 上市不足 250 个交易日的新股：各条均线只在达到对应 N 日后开始，不出现 0 轴横线或垂直跳线；未成熟均线的顶部值显示 `--`。
2. 上市超过 250 个交易日的老股：七条均线、默认窗口、缩放、拖动和十字光标行为与修正前一致。

验收截图至少包含：新股页面初始状态、hover 在 MA5 形成前、hover 在 MA5 形成后、老股页面对照。

## 5. 边界与风险

1. 本轮不修改 `equity_factor_pro` 的 MA 公式，不进行历史数据重算或数据迁移。
2. 本轮不在前端重新计算 MA，也不根据返回条数推断上市天数。
3. 本轮只修股票详情日线；分钟线和指数详情不做附带修改。指数详情仅作为已验证实现基线。
4. `0` 仍是一个有限数值，前端不会擅自把真实 `0` 解释成缺失；缺失必须由数据合同明确返回 `NULL`。
5. 若页面验收发现 API 对预热期直接返回 `0`，必须回到 `equity_factor_pro` 生产链路单独审计，不能在图表层增加 `value === 0` 的经验过滤。

## 6. 完成定义

以下条件全部满足才算完成：

- 七个 MA 的 `NULL` 从 API 到图表全链路不丢失。
- 第 N 根之前没有 `MA_N` 数值点，第 N 根开始正常绘制。
- 页面不存在由缺失 MA 造成的 0 轴横线和垂直跳线。
- 顶部指标栏缺失值显示 `--`。
- 新股与老股页面验收通过。
- 日线 API、路由、查询性能、图表 viewport 和其它指标行为无回退。

## 7. 实施结果

1. 股票日线 MA 已改为 `number | null`，API adapter 不再执行 `NULL -> 0`。
2. Mock MA 已按完整窗口计算，第 N 根之前保持 `NULL`。
3. 后端 API 回归证明数据库 `NULL` 原样输出为 JSON `null`。
4. 前端回归证明空 MA 生成 whitespace，指标栏显示 `--`，不产生 0 数值点。
5. 本地页面 `688635.SH` 已验收：MA60/90/250 显示 `--`，主图无 0 轴横线或垂直跳线；MA5/10/20/30 从各自有效位置开始。
6. 分钟线未纳入本次实现，后续按独立专项设计分钟 MA 数据合同和 bounded 计算链路。
