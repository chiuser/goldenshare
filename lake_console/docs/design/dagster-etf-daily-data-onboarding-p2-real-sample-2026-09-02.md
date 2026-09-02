# ETF 日线与复权因子 DG 接入 P2 最小真实样本验收

> 状态：通过
> 验证时间：2026-09-02 14:48 CST
> 被验代码：`f5f62134 feat(lake): add ETF daily raw ingestion`
> 样本日期：`2026-09-01`
> 边界：只读 Tushare，只写 `/private/tmp`；未运行 Dagster job，未写 Dagster event，未读写正式 Lake

## 1. 结论

P2 最小真实样本验收通过。当前 Raw writer 能按冻结合同完成两个接口的真实分页、逐页 DuckDB 累积、候选回读审计和原子提升，未发现字段、类型、日期、主键、行数或分页偏差。

本次只验证一个日期、两个接口，不是历史同步，也没有进入 P3 Silver。

## 2. 执行范围

- 隔离根目录：`/private/tmp/etf-daily-p2-real.OJTu1C`
- 临时 Lake：`/private/tmp/etf-daily-p2-real.OJTu1C/data_lake`
- 临时 staging：`/private/tmp/etf-daily-p2-real.OJTu1C/data_lake_staging`
- DuckDB 临时目录：`/private/tmp/etf-daily-p2-real.OJTu1C/duckdb_tmp`
- `fund_daily`：`limit=5000`，最多 2 次请求
- `fund_adj`：`limit=2000`，最多 4 次请求
- 实际总请求数：3，无重试

## 3. 真实结果

| 接口 | 源端/归一化/候选/写入 | 页与 offset | 文件大小 | 耗时 | Content hash |
| --- | ---: | --- | ---: | ---: | --- |
| `fund_daily` | `2105 / 2105 / 2105 / 2105` | 1 页：`0` | 65,927 B | 618.812 ms | `44f8759f4751e5ced0e12c06cf148611d67f85546fabf56978ca30a37558e331` |
| `fund_adj` | `2138 / 2138 / 2138 / 2138` | 2 页：`0, 2000` | 16,936 B | 205.485 ms | `5687c58c2860fff6c6afef801135d0ceabba32285688104168d61d0232998db3` |

两个目标都以 `write_new` 写入隔离 Lake，候选提升后 staging Parquet 残留为 0。

## 4. 合同与数据检查

两个文件均满足：

- columns 和类型顺序与冻结 Raw schema 完全一致；
- 文件内 `trade_date` 全部为 `20260901`；
- 主键空值为 0；
- `ts_code + trade_date` 重复为 0；
- 源端、归一化、候选和写入行数一致；
- 候选文件可读，审计错误码为空；
- DuckDB spill 文件数为 0；进程最大 RSS 为 229,064,704 B。

源端事实保留也符合方案：

- `fund_daily` 后缀分布为 `.OF=1, .SH=1093, .SZ=1011`，Raw 没有过滤 `.OF`；
- `fund_adj.discount_rate` 有 7 个空值，样本最小值 `-72.4787`、最大值 `47.2116`，Raw 没有填充或裁剪。

## 5. 安全边界

- 没有使用 `/Volumes/datasource/data_lake`；
- 没有使用 `/Volumes/datasource/data_lake_staging`；
- 没有运行正式 Dagster job；
- 没有写入 materialization 或 asset check event；
- 没有执行 Bootstrap、历史全量或 Sensor；
- 没有读取 ETF Basic，符合 Raw 与 Basic 解耦要求。

## 6. 阶段结论

P2 已完成，可以进入 P3 Silver 开发。隔离样本只证明当前 writer 对该真实日期和当前源合同有效，不授权正式 Lake 写入或历史回补。
