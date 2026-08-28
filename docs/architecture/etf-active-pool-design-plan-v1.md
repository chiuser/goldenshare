# ETF 激活池历史设计与退场记录 v1

状态：历史机制；运行时、运维入口和代码基础设施已退场，生产物理表待独立维护窗口删除
创建日期：2026-06-17
退场日期：2026-08-29
替代方案：[ETF 基础信息重建与下游数据审计清理技术方案 v1](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-plan-v1.md)

本文只保存旧机制为什么出现、曾经覆盖什么、如何退场的历史证据，不再是可执行方案。任何新开发都不得据此恢复旧表、seed、CLI、Review 页面或第二套 ETF 清单。

## 1. 历史背景

旧机制使用 `ops.etf_series_active` 保存按 `(resource, ts_code)` 区分的 ETF 代码集合，先后承载五个 resource：

| resource | 历史用途 |
| --- | --- |
| `fund_daily` | 从基金日线源端全集中筛选 ETF serving 行 |
| `etf_mins` | 展开 ETF 历史分钟请求 |
| `etf_sh_cons` | 展开上交所 ETF 申赎清单请求 |
| `etf_sz_cons` | 展开深交所 ETF 持仓组合请求 |
| `etf_rt_daily` | 实时 Health、监控候选和旧 Review 展示 |

它解决了早期“没有统一 ETF 主数据资格契约”的问题，但后来形成了第二份需要 seed、人工复核和持续维护的对象清单。代码、上市状态和上市日与每天更新的 ETF Basic 重复，且分钟请求无法天然从上市日开始。

## 2. 退场原因

当前设计已确认：ETF 身份与新增请求资格必须由 `core_serving.etf_basic` 的统一 selector 提供，不能再由各 resource 保存一份静态名单。

统一的当前可请求条件是：

```text
list_status = 'L'
AND list_date IS NOT NULL
AND list_date <= 本次业务操作开始时固定的中国自然日
AND ts_code 仅限 .SH / .SZ
AND ts_code 后缀与 exchange 一致
```

旧池退场带来的直接结果：

1. 新上市 ETF 在 Basic 更新后自动进入下一次规划，不再等待 seed。
2. 代码驱动请求可以从 `list_date` 起算，避免请求上市前数据。
3. 显式单代码和全量任务使用同一资格规则。
4. 不再存在激活池 DAO、seed CLI、Review 页面或兼容读取。
5. `ops.index_series_active` 是独立的指数机制，完整保留。

## 3. 当前替代关系

| 能力 | 当前机制 |
| --- | --- |
| `etf_mins` | 每次 plan 固定中国自然日；全量加载一次 Basic requestability snapshot，显式代码只查一次 target；起点裁到 `list_date` |
| `etf_sh_cons` | 同一 Basic selector，并限定 `exchange='SH'` |
| `etf_sz_cons` | 同一 Basic selector，并限定 `exchange='SZ'` |
| `fund_daily` | 源请求仍按交易日拉全市场；raw 先提交，ETF serving 再按 Basic 当前资格和上市日发布 |
| 实时 Health | 每次 Health API 请求读取一次当前 Basic snapshot，返回 `eligible_*` 指标 |
| 实时监控候选与运行时 | 候选从 Basic requestable subquery 起表；运行时只处理“启用监控池 ∩ 当前可请求 ETF” |
| ETF Review | 页面和 API 已直接删除，没有 Basic 替代页面 |

`fund_adj` 和 `etf_share_size` 从未需要按这个静态池展开：前者保存基金源端全集，后者每个交易日请求一次 ETF 份额规模全市场结果并 raw 直出 serving。

## 4. 历史生产快照

2026-08-29 退场前只读审计记录：生产旧表共 5,708 行。

| resource | 行数 |
| --- | ---: |
| `fund_daily` | 1,395 |
| `etf_mins` | 1,395 |
| `etf_rt_daily` | 1,395 |
| `etf_sh_cons` | 803 |
| `etf_sz_cons` | 720 |

该表只有自身主键和两个索引，没有外键、依赖视图、自定义触发器或函数依赖。上述数量只是带日期的历史审计证据，不是当前 ETF 全集、请求门禁或未来容量常量。两份旧 seed CSV 在退场时均不存在，因此没有“删除 seed 文件”的交付事实。

## 5. 退场顺序

退场按消费者先行完成：

1. P3：迁移三个代码驱动 planner。
2. P4：迁移 `fund_daily` serving，并删除旧 cleanup。
3. P5：迁移实时 Health。
4. P6：迁移实时监控候选、写入门禁和运行时交集。
5. P7：删除 ETF Review API/UI，证明运行时消费者为零。
6. P8：删除 model、DAO、contract、adapter、seed、CLI、装配和专属测试；准备不可逆 drop migration。
7. P11：只有取得独立生产维护窗口授权后，才物理删除生产表。

## 6. Schema 历史与当前边界

历史建表 migration `20260618_000117_add_etf_series_active.py` 必须保留在 Alembic 链中。P8 新增 `20260829_000157_drop_etf_series_active.py`，只执行精确的 `DROP TABLE ops.etf_series_active`，不使用 `CASCADE` 或 `IF EXISTS`，downgrade 明确拒绝恢复旧表。

P8 代码完成不等于生产表已经删除。本阶段不备份、不迁移 5,708 行，也不执行生产 DDL。生产物理删除、版本发布和 ETF Basic 正式重建统一留给 P11 的独立授权。

## 7. 永久禁止项

1. 不恢复旧池 model、DAO、contract、adapter、seed 或 CLI。
2. 不新增空实现、alias、fallback、双读或兼容页面。
3. 不把历史 1,395/803/720 数量重新固化为业务规则。
4. 不把 `etf_rt_min`、DG ETF 接入等未重新基线的未来方案擅自接到 Basic 或另一个持久化池。
5. 不误删或改造 `ops.index_series_active`。
