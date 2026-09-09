# Ops 数据集展示目录 v1

状态：当前代码说明；2026-09-09 校准。原文“展示分组清单待最终确认”未找到独立结案证据，见 §5；本次不调整实际分组。

## 1. 目录解决什么问题

同一外部数据集在数据源卡片、手动维护和自动任务里应使用同一展示分组。**业务领域、页面分组、任务能力是三件事**，不能相互替代。

| 事实 | 归属与用途 |
| --- | --- |
| 外部数据集身份、领域、来源、日期和维护能力 | Foundation `DatasetDefinition`；`domain_*` 保留底层领域含义 |
| 外部数据集展示分组与顺序 | Ops `dataset_catalog_views.py` 的 `ops_dataset_default` |
| Biz 卡片身份、分组、观测与生产入口 | Ops `BizDatasetDefinition`，见 [Biz 投影契约](/Users/congming/github/goldenshare/docs/ops/ops-biz-dataset-auto-projection-plan-v1.md)；不套用外部数据集目录 |
| Workflow / maintenance action 分组 | 各自 action/workflow 定义；不是 dataset_key 到目录的映射 |
| 卡片/任务/审计 API 字段 | [Ops API 参考](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md) |

这里的页面使用方是运营，不是行情系统终端用户。前端消费后端返回的 `group_*`，不复制数据集分组表；目录不反向改变 freshness、业务日期或生产链路。

## 2. 当前配置与解析边界

代码入口：

- [默认配置](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py)：`DatasetCatalogGroup / DatasetCatalogItem / DatasetCatalogView`，默认 view key 为 `ops_dataset_default`。
- [解析与校验](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_view_resolver.py)：`resolve_item()` 返回 group、item_order、visible；`validate_default_dataset_catalog()` 对账注册表。
- [架构测试](/Users/congming/github/goldenshare/tests/architecture/test_ops_dataset_catalog_view.py)：完整注册表覆盖与部分前端旧映射标记检查。

配置仍在代码中，不在数据库、env 或运营可编辑表单中；改变配置需要发布相应代码。当前只有一个默认外部数据集目录，没有用户自定义目录、持久化目录表或页面专属 view。

字段职责：

| 模型 | 字段与含义 |
| --- | --- |
| DatasetCatalogGroup | `group_key, group_label, group_order, description`：组身份、名称、顺序和说明 |
| DatasetCatalogItem | `dataset_key, group_key, item_order, visible`：数据集归组及组内顺序；visible 当前只是定义/解析字段，见下文限制 |
| DatasetCatalogView | `view_key, groups, items`：一个目录的完整配置 |

校验范围是**全部注册的 DatasetDefinition**，不只是 manual/schedule enabled 的子集。缺配置、重复 dataset_key、未知数据集、未知分组、相同 group_key 的 label/order 冲突均报错；resolve_item 缺项直接抛配置异常，不兜底到“其他”。

当前目录包括 A股财务数据、公募基金等后续新增分组，旧第 10 节表格已不完整，顺序也与代码不同。逐数据集归属只维护在默认配置，不再复制数十行“当前/目标/旧手动分组”对照表。

**不要把模型字段当成已完成能力：**

- `visible` 被配置和返回，但当前 card/manual/catalog/date completeness 查询未按它统一过滤；不能承诺改成 false 就能隐藏入口。本次不启用或修改该字段。
- Resolver 只负责解析与静态校验；source、manual_enabled、schedule_enabled 等筛选分别在消费方完成，不是 resolver 自带多条件过滤 API。
- 当前前端架构测试检查 source/auto/audit 三个文件中的特定旧标记，不是对全部页面行为的完备证明；后续改动还须核验实际消费方。

## 3. 各入口实际如何使用

| 消费方 | 当前行为与边界 |
| --- | --- |
| 数据源/总览卡片：DatasetCardQueryService | 从 Definition 取事实；按来源和 logical_key 选择/合并，再解析展示目录；按 group_order、item_order、display_name、card_key 排序 |
| 手动维护：ManualActionQueryService | 外部 dataset action 使用默认目录，按动作支持能力选取；Workflow、maintenance 使用各自定义的分组 |
| 自动任务：CatalogQueryService 与自动任务页 | dataset action 返回默认目录的 group_*；可排程能力仍由 automation_capability 决定，不从分组推断 |
| 日期完整性规则：DateCompletenessRuleQueryService | item 内使用默认目录；**外层 groups 仍是 supported/unsupported**，页面用 item.group_* 做目录筛选 |
| Biz 数据源卡片 | 使用独立 Biz 定义的四组，不进入 ops_dataset_default；复用同一卡片 API 与组件，不等于共用目录事实源 |

外部卡片分组与逻辑去重是不同层次；不能承诺一条 Definition 在所有来源页都恰好对应一张卡片。日期审计的“支持/不支持”也不能被页面目录覆盖。

## 4. 后续维护与回归

新增外部数据集时补齐默认目录，并对账注册表；如要改变现行分组或隐藏行为，先获得明确批准。无需为纯展示调整修改 Definition.domain、业务表、任务执行器或数据。

最小核验：

1. 目录无缺项/重复/未知引用，组名与组顺序一致。
2. 卡片、手动、自动的同一外部数据集分组一致；Workflow/maintenance/Biz 不误入外部目录。
3. 审计规则 item 使用目录，但外层能力分组不变。
4. 前端不自建映射，不把 domain_* 当作数据集展示分组；保留服务端排序。
5. 文档变更只跑静态对账、链接及文档完整性检查；实际分组/查询行为改动再补相关 API/页面回归。

## 5. 历史决定与未决边界

已确认的 D1～D5 保留：一个默认目录、审计页也接入、展示字段使用 group_*、缺目录报错、不做用户自定义分组。原 M1～M8 的实现步骤不再作为待开发清单。

原文标题与第 10 节仍标“分组清单待最终确认”，没有可据此认定已拍板的独立结案记录。本次只描述当前配置，**不将已编码等同于分组方案已获最终批准**；若运营仍要重新确认名称或归属，以当次代码配置清单评审，不用过期表覆盖现状。

旧方案提出的用户目录表和多 view 仅是后续设想，未实现、未新增为本轮任务。本文也不证明当前生产版本或页面已经验收。
