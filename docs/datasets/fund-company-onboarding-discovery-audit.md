# 基金管理人（`fund_company`）接入发现审计

状态：**发现审计、B1 LLD、代码实现、隔离验收与生产迁移/首次完整同步/五段对账均已完成；尚未创建 schedule。**
首次审计：2026-08-03；源端复审：2026-08-05；代码与生产状态复核：2026-08-10
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

## 已落地的接入轮廓

| 层次 | 当前实现 |
| --- | --- |
| 时间输入 / unit | 仅 snapshot refresh，一个全量 unit。 |
| freshness / audit | 不做连续日期完整性；卡片显示最近一次成功快照。 |
| 身份 / 幂等 | 非空 `credit_code` 使用规范化信用代码身份；空 `credit_code` 依次使用 `name + setup_date` 内容散列或全字段内容散列兜底，不把无法证明同一的记录自动合并。 |
| 存储 | direct-serving；全部 18 个字段进入 `core_serving.fund_company_current` 与 `core_serving.fund_company_observation`，表和索引固定 HDD。 |
| Ops/UI | 归入新增“公募基金”目录；不得落入现有“ETF基金”或静默“其他”。 |
| 自动化 | 支持手动和普通 cron/once 定时任务；无 probe、workflow 或自动 schedule seed。 |

当前仓库已具备完整接入链路：`src/foundation/datasets/definitions/public_fund.py` 注册 DatasetDefinition，B0 observed-snapshot writer 负责完整快照发布，显式 ORM/DAO 已注册，migration `20260805_000125` 创建 current/observation 两表并强制 HDD，Ops Catalog 已注册“基金管理人”。生产 TaskRun `#7401` 完成 204 行首次完整同步：source/normalized/written/current/observation 均为 204，reject 0；同一信用代码的两个源内容变体均被保留。

## 已落地的身份与版本口径

1. 非空 `credit_code` 是公司实体的权威身份；相同信用代码但名称不同的行进入同一公司的观察版本历史，绝不静默丢弃其中一行。
2. 对 49 条空信用代码，为了完整保存而又不把无关机构误合并，使用规范化 `name + setup_date` 作为内部保守身份；后续名称变化不自动认定为同一公司。
3. 每个公司身份保留当前记录和观察版本：全部 18 个源字段、内容散列、首次/最后一次观察时间都要保存。历史从接入日开始，不能伪称为源端生效历史。
4. `main_business`、地址、电话等全部保存；是否在前端默认展示不改变存储完整性，留待 LLD 的查询/UI 设计决定。

## 2026-08-05 批次固定约束

本数据集的每一个源端返回字段均必须显式列入 `source_fields` 并保存；所有物理数据对象放 HDD；Ops 只能暴露手动和普通定时任务，不能暴露 probe。
