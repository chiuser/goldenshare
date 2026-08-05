# 基金管理人（`fund_company`）接入发现审计

状态：发现审计完成；B1 LLD 已起草，**未开发、未建表、未写入远程数据**
首次审计：2026-08-03；复审：2026-08-05
截图菜单：基金管理人
源文档：[公募基金公司](../sources/tushare/公募基金/0118_公募基金公司.md)

## 结论

`fund_company` 可完整取得当前基金管理人快照：无参数实测 204 行，显式请求全部字段同为 204 行。它适合作为低频、无时间轴的主数据；机构身份采用业务已确认的统一社会信用代码，但必须处理源端空代码。

## 源端事实与实测

| 项目 | 已核验事实 | 接入含义 |
| --- | --- | --- |
| 参数 | 无业务参数；源文档称可一次取得全部 | 定义应为 `none` / snapshot，不暴露时间控件。 |
| 默认字段 | 17 个字段；`short_enname` 未默认返回 | 必须显式请求 18 个字段。 |
| 显式全部字段 | 204 行，含 `short_enname` | 字段契约已能建立。 |
| 分页 | MCP schema 未展示，但项目 `TushareHttpClient` 实测 `limit=64` 的页长 `[64,64,64,12]`；分页并集 204 行与无参基线完整行多重集一致 | 配置 `offset_limit`、`page_limit=64`，仅短页结束；不设置最大页数。 |
| 身份 | `credit_code` 非空 155 行、空值 49 行；同一非空代码 `91440400MA4UH0BF7C` 对应两条不同名称、相同组织代码/成立日的记录 | 非空 `credit_code` 是业务确认的公司身份；名称差异是同一实体的观察版本，不能当作两家公司。空代码不能作为同一实体合并。 |

候选 `source_fields`：

```text
name, shortname, short_enname, province, city, address, phone, office,
website, chairman, manager, reg_capital, setup_date, end_date, employees,
main_business, org_code, credit_code
```

## 建议的接入轮廓（非 LLD）

| 层次 | 建议 |
| --- | --- |
| 时间输入 / unit | 仅 snapshot refresh，一个全量 unit。 |
| freshness / audit | 不做连续日期完整性；卡片显示最近一次成功快照。 |
| 身份 / 幂等 | 非空 `credit_code` 为公司自然身份；空 `credit_code` 用规范化 `name + setup_date` 生成保守内部身份，名称变化时不自动跨记录合并。 |
| 存储 | 全部 18 个字段均保存；物理表、叶分区和索引固定 HDD，direct-serving/raw->serving 在 LLD 固化。 |
| Ops/UI | 归入新增“公募基金”目录；不得落入现有“ETF基金”或静默“其他”。 |
| 自动化 | 支持手动和普通定时自动任务；本期不接 probe。 |

仓库没有 `fund_company` 接入代码。通用链路已有 DatasetDefinition → resolver → source client → writer → Ops catalog 入口，但 Definition、模型、DAO、迁移、runtime guard、catalog 和前端消费者都仍待实现。

## 已冻结的身份与版本口径（非 LLD）

1. 非空 `credit_code` 是公司实体的权威身份；相同信用代码但名称不同的行进入同一公司的观察版本历史，绝不静默丢弃其中一行。
2. 对 49 条空信用代码，为了完整保存而又不把无关机构误合并，使用规范化 `name + setup_date` 作为内部保守身份；后续名称变化不自动认定为同一公司。
3. 每个公司身份保留当前记录和观察版本：全部 18 个源字段、内容散列、首次/最后一次观察时间都要保存。历史从接入日开始，不能伪称为源端生效历史。
4. `main_business`、地址、电话等全部保存；是否在前端默认展示不改变存储完整性，留待 LLD 的查询/UI 设计决定。

## 2026-08-05 批次固定约束

本数据集的每一个源端返回字段均必须显式列入 `source_fields` 并保存；所有物理数据对象放 HDD；Ops 只能暴露手动和普通定时任务，不能暴露 probe。
