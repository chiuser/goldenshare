# 基金净值（`fund_nav`）接入发现审计

状态：发现审计完成，**未进入 LLD、未建表、未写入远程数据**
首次审计：2026-08-03；复审：2026-08-05
截图菜单：基金净值
源文档：[公募基金净值](../sources/tushare/公募基金/0119_公募基金净值.md)

## 结论

`fund_nav` 是基金净值的明确接口，支持按基金或净值日查询；单基金 `000001.OF` 返回 5,984 个历史净值且 `(ts_code, nav_date)` 唯一。场外单日分页已验证：`market=O, nav_date=20260617`、10 个显式字段、`limit=2000` 共 12 页，末页 598 行，共 **22,598 个唯一 `(ts_code, nav_date)`**。此前 10,500 只是单页结果，不是场外总量。

## 源端事实与实测

| 项目 | 已核验事实 | 接入含义 |
| --- | --- | --- |
| 必填组合 | 无参数报错：`ts_code` 与 `nav_date` 至少一个；只传全市场 `start_date/end_date` 也报同一参数校验错误 | 不是无日期快照接口；全市场不能把区间直接传给源端。 |
| 单基金历史 | `000001.OF` 5,984 行，2001-12-18..2026-08-03 | `ts_code` 可取历史，但全市场范围另论。 |
| 日期点分页 | 2026-06-17：O 为 `2000×11 + 598 = 22,598` 行 | O 全市场按日期可完整分页；E 也应作为独立市场分片保存。 |
| 市场返回边界 | `market=O` 的末页还含 7 个 `.SZ` 代码（`169102.SZ`、`169103.SZ`、`169107.SZ`、`501054.SZ`、`501066.SZ`、`161907.SZ`、`168002.SZ`），且不在同日 E 结果中 | 以请求市场分片做来源身份，不能按代码后缀拒绝或擅自归类，避免漏行。 |
| 短区间 | 单基金 `000001.OF` 的 2026-06-16..17 为 2 行 | 范围可作为单基金查询；不等于全市场支持区间请求。 |
| 字段差异 | 文档为 9 字段；默认实际多出 `update_flag`，且显式请求 10 字段成功 | `update_flag` 必须纳入真实字段契约；本地文档要校准。 |
| 分页 | MCP 和项目客户端均实测接受 `limit/offset`，末页 short page 正常终止 | 使用 `offset_limit`，每页都请求同一 10 字段。 |
| 当日可用性 | 2026-08-05 11:17 CST，显式请求 E/O 两市场 `nav_date=20260805` 均为空；前一日 2026-08-04 的 O 市场已有 10,500 行 | 在“不做 probe”前提下，自动任务不能把触发当日当作已发布净值日。 |

已确认、后续 Definition 必须原样使用的 `source_fields`：

```text
ts_code, ann_date, nav_date, unit_nav, accum_nav, accum_div, net_asset,
total_netasset, adj_nav, update_flag
```

`nav_date` 是净值所属日，`ann_date` 是公告日；两者都要保存。`market` 虽是请求分片却不在输出字段，必须以系统字段 `source_market_scope` 保存请求市场，并加入逻辑身份，防止同一 `(ts_code, nav_date)` 跨 E/O 分片发生静默覆盖；不能从代码后缀反推请求市场。

## 建议的接入轮廓（非 LLD）

| 维度 | 当前建议 |
| --- | --- |
| 时间输入 | `nav_date` point/range；范围是 resolver 层意图，必须展开为逐个自然日的 `nav_date` point unit，不能生成全市场 `start_date/end_date` 源端请求。`every_natural_day` 的 range 展开必须成为通用 planner 能力，不能写成 `fund_nav` 特判。 |
| 执行 / 完整性 | 暂不做连续日 audit：场外基金非交易日、公告滞后和修订均可能存在。 |
| 分页 / 范围 | E/O 各自按 `nav_date` 分页；O 是不可降级的全市场范围。 |
| 更新时机 | 两个普通定时自动任务：每日最新净值日更新，以及每周最近 90 个自然日修订；本期不接 source/freshness probe。 |
| 存储 / UI | 所有 10 源字段均保存；新“公募基金”目录；表/叶分区/索引固定 HDD。 |

## 已冻结的身份、修订与调度口径（非 LLD）

1. **范围**：E/O 全市场均保存；O 分页完整性已验证，不能退回 ETF 池。
2. **逻辑身份**：`(source_market_scope, ts_code, nav_date)`；`ann_date` 是内容字段，不是身份字段。
3. **修订保存**：维护当前记录和观察版本。每个观察版本保存 10 个源字段、`source_market_scope`、内容散列和首次/最后一次观察时间；同一逻辑身份内容变化时关闭旧观察版本、写入新版本。`update_flag` 原样保存并进入内容散列，但在未核实业务语义前，不得单独决定覆盖、去重或修订。
4. **建议的自动化相对时间策略**：两个同一 `maintain` action 的独立普通 schedule 均由后端在触发时解析，前端和 `params_json` 不保存固定日期。以 Asia/Shanghai 触发日 `D` 计算：日任务为 `[D-1, D-1]`；周修订为 `[D-90, D-1]`（含首尾共 90 个自然日）。这是“上一个已完成自然日”策略，不是 probe，也不声明源端某个时刻一定发布当日数据。
5. **建议的系统管理策略契约**：相对时间策略应新增为 schedule-side 的共享、受校验、不可由页面自由拼装的 `time_policy`；现有 `calendar_policy` 只承载月末/触发日旧策略，不能继续堆叠成数据集特例。TaskRun 只落本次已解析的绝对时间输入与 plan snapshot，保证可审计、可重试。
6. **建议的重叠防护**：创建 TaskRun 前必须先解析 `DatasetExecutionPlan`，以其规范化 E/O `nav_date` unit 建立活动租约。`queued`、`running`、`canceling` 的租约均视为占用；日任务和 90 日任务有交集时，后到的自动触发跳过并记录 `duplicate_active_unit_scope`，手工/重试请求返回冲突，不能再生成一个排队任务。终态任务自然释放占用。该 admission contract 是共享能力，不能依赖当前只存不执行的 `concurrency_policy_json`。
7. **LLD 前实现门禁**：现有 schedule 只能保存静态时间输入，`concurrency_policy_json` 没有运行时消费者，且 `natural_day` range 会退化为一个整段源请求。因此必须先落共享相对时间策略、通用逐自然日 unit 展开、按解析 unit 的活动租约和版本化 direct-serving writer；否则不能创建两条自动任务。
