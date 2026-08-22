# 公募基金业绩基准库（`mkt_idx_bmk`）接入发现审计

状态：**发现审计、B1 LLD、代码实现、隔离验收与生产迁移/首次完整同步/五段对账均已完成；尚未创建 schedule。**
首次审计：2026-08-03；复审与结论纠正：2026-08-05；代码与生产状态复核：2026-08-10
截图菜单：基金业绩基准
源文档：[公募基金业绩基准库](../sources/tushare/公募基金/0462_公募基金业绩基准库.md)

## 结论

早期“没有独立接口”的判断不正确。`mkt_idx_bmk` 是可独立接入的**基准指数参考库**：当前实测 141 行，返回 8 个字段。它不返回基金代码与基准的对应关系，不能替代 `fund_basic.benchmark` 的“某基金当前基准文本”。

因此截图菜单的“基金业绩基准”已经按独立 DatasetDefinition、独立存储和独立维护动作接入；`fund_basic.benchmark` 仍作为基金列表的完整源字段保存。两张表不根据文本自行做关联或覆盖。

## 源端事实与实测

| 项目 | 已核验事实 | 接入含义 |
| --- | --- | --- |
| 接口 | `mkt_idx_bmk`，当前 Tushare MCP 将其归在 ETF 专题 | 源端分类不决定 Ops 产品分组；Ops 归“公募基金”。 |
| 输入 | `ts_code`、`BMK_TYPE` 可选 | 是参考库筛选，不是基金映射条件；不得把它们自动暴露为运营输入。 |
| 返回 | 141 行、8 个字段 | 当前体量小，但仍显式请求全部字段。 |
| 时间 | 无生效日、公告日或历史版本字段 | 只能记录接入后的观察版本，不能伪造源端历史。 |
| 分页 | MCP schema 未展示，但项目 `TushareHttpClient` 实测 `limit=64` 的页长 `[64,64,13]`；分页并集 141 行与无参基线完整行多重集一致 | 配置 `offset_limit`、`page_limit=64`，逐页固定 8 字段，短页结束且不设最大页数。 |

已确认、后续 Definition 必须原样使用的 `source_fields`：

```text
ts_code, symbol, name, fullname, bmk_level, bmk_type, bmk_src, idx_type
```

## 已落地的接入轮廓

| 维度 | 当前实现 |
| --- | --- |
| 时间输入 / unit | `none` / snapshot refresh，一个参考库快照 unit；不暴露日期控件。 |
| 身份 / 历史 | 逻辑身份为 `ts_code`；维护当前记录和观察版本，版本保存 8 个源字段、内容散列和首次/最后一次观察时间。观察历史从接入日开始。 |
| 关联边界 | 不把 `fund_basic.benchmark` 的自由文本自动解析或关联到本库；前者是基金映射文本，后者是指数参考条目。 |
| 存储 / Ops | direct-serving；全部字段进入 `core_serving.mkt_idx_bmk_current` 与 `core_serving.mkt_idx_bmk_observation`，表和索引放 HDD；Ops 归“公募基金”，仅手动 + 普通定时任务、无 probe。 |

## 已完成的实施与验收

1. 项目 connector 已证明 `64/64/13` 分页、短页结束和 8 字段完整契约；分页并集与无参 141 行基线一致。
2. DatasetDefinition 已注册在 `src/foundation/datasets/definitions/public_fund.py`，复用 B0 observed-snapshot writer，但保持独立 Definition、两张显式表和独立维护动作。
3. migration `20260805_000125` 已在生产创建 current/observation 两表并强制 HDD；DAO factory、table registry 与 Ops Catalog 均已注册。
4. 生产 TaskRun `#7402` 完成 141 行首次完整同步：source/normalized/written/current/observation 均为 141，reject 0；current 与 observation 集合一致。
5. 自动化能力仅允许手动与普通 cron/once 定时任务；无 probe、workflow 或自动 schedule seed。
