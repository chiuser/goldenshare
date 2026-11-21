# DG 已确认业务事实接入使用说明

更新 2026-11-21 · 适用于接入登记表的数据集开发与维护人员

DG 用一张登记表保存有明确证据、生效日期和适用对象的业务事实。运营登记一次，相关数据集按自己的规则读取。以天弘上证180ETF（`530080.SH`）为例，Tushare 的 ETF 基础信息仍给出 `L`，基金公告确认 11 月 16 日进入清算。DG 基金状态查询使用这条事实显示「清算中」，ETF 复权因子则用它判断该基金当天是否必须有因子。 [登记方案](dagster-confirmed-business-facts-plan-v1.md) · [正式验收实例](dagster-confirmed-business-facts-low-level-design-v1.md#formal-recovery-results)

## 1. 判断数据集是否需要接入

先明确一个可以验收的业务判断，例如「ETF 进入清算后，缺少当天复权因子是否阻断检查」。如果数据集需要根据已确认事实改变这种判断，就在对应的检查或查询入口接入。只保存来源原始数据的任务照原流程运行。

接入前确定对象类别、事实类型、生效日期的含义和所需日期范围。现有维护命令支持沪深 ETF，对象类别为 `etf`，代码格式为六位数字加 `.SH` 或 `.SZ`。现有类型如下。

| 事实类型 | 需要的证据 | 已验证的用途 |
| --- | --- | --- |
| `fund_liquidation_started` | 基金管理人公告确认进入清算的生效日期 | 基金状态显示「清算中」，ETF 复权因子覆盖检查据此判断能否缺省 |
| `fund_delisted` | 交易所公告确认的正式终止上市日期 | 基金状态显示「退市」 |

基金状态查询依次采用生效的正式退市事实、生效的清算事实、来源状态。每个数据集应明确自己使用哪些事实类型。新的对象类别或事实类型需要补充编码、维护校验和业务测试后再接入。 [事实类型和基金状态实现](../../orchestrator/src/orchestrator/defs/confirmed_business_facts.py)

## 2. 登记并读回一条事实

在 `lake_console/orchestrator` 目录，使用现有 `.venv/bin/python3 -B`。登记、更正、撤销使用具名维护连接 `LAKE_META_POSTGRES_WRITE_URL`，查历史和基金状态使用只读连接 `LAKE_META_POSTGRES_URL`。手工命令执行前，把对应连接变量提供给当前命令环境。DG 的任务使用项目配置中的只读连接。连接和权限的实际配置见详细设计。 [正式连接和权限](dagster-confirmed-business-facts-low-level-design-v1.md#formal-recovery-runbook)

这次 `530080.SH` 已经完成正式登记。以下是实际登记用法，新增一条事实时按获准的对象和证据替换各项。

```sh
.venv/bin/python3 -B -m orchestrator.defs.confirmed_business_facts_cli register \
  --subject-key 530080.SH --fact-type fund_liquidation_started \
  --effective-from 2026-11-16 --reason '份额持有人大会决议，基金自该日起进入清算' \
  --evidence '天弘基金' 'https://qcloud.fund.eastmoney.com/gonggao/530080%2CAN202611141831712627.html' 'AN202611141831712627'
```

| 输入 | 怎么填 |
| --- | --- |
| `--subject-key`、`--fact-type` | ETF 代码和固定事实编码 |
| `--effective-from` | 公告确认的生效日，按上海时间从当天零点起生效 |
| `--effective-until` | 可选，填写后从该日零点起停止适用。缺省表示目前没有已确认的结束日期 |
| `--reason` | 简述为何登记或更正，便于查阅 |
| `--evidence` | 发布机构、公告链接、可选公告编号。多份依据可重复提供此参数 |

成功时命令返回 JSON。初次登记会返回 `fact_id` 和 `revision=1`，还会返回生效区间、公告、操作人和登记时间。本次的事实编号为 `30a33ad9-6684-4824-b818-b7fb05352339`。可按 ETF 代码列出历史，也可按事实编号定位。

```sh
.venv/bin/python3 -B -m orchestrator.defs.confirmed_business_facts_cli history \
  --subject-key 530080.SH --limit 10

.venv/bin/python3 -B -m orchestrator.defs.confirmed_business_facts_cli history \
  --fact-id 30a33ad9-6684-4824-b818-b7fb05352339 --limit 10
```

基金状态用 `fund-status` 查询。当天查询需设置正式 `DAGSTER_HOME`，使用当日最新且通过检查的 ETF 基础信息。历史查询需要把原运行的 `goldenshare/basic_reference` JSON 保存为文件，再通过 `--basic-reference` 传入。

```sh
.venv/bin/python3 -B -m orchestrator.defs.confirmed_business_facts_cli fund-status \
  --subject-key 530080.SH --date "$(TZ=Asia/Shanghai date +%F)"

.venv/bin/python3 -B -m orchestrator.defs.confirmed_business_facts_cli fund-status \
  --subject-key 530080.SH --date 2026-11-17 --basic-reference "$DG_ORIGINAL_BASIC_JSON"
```

`DG_ORIGINAL_BASIC_JSON` 指向从目标运行取得的引用 JSON 文件。11 月 21 日更新后的正式核验返回 `source_status="L"`、`status="清算中"`、第 `1` 版事实及基础信息指纹。 [维护命令实现](../../orchestrator/src/orchestrator/defs/confirmed_business_facts_cli.py)

## 3. 在数据集程序中读取

只给需要读取事实的任务或检查绑定 `confirmed_business_facts` 资源。传入对象类别、需要的固定类型、开始日和不含结束日的日期窗口。单日检查只查当天。sensor 对它已有的批次查一次，随后用 `applies_on(day)` 为每个交易日筛选。以下代码演示在同一批次读取 11 月 17–19 日适用的 ETF 清算事实。

```python
from datetime import date, timedelta

from orchestrator.defs.confirmed_business_facts import FactType
from orchestrator.defs.resources import ConfirmedBusinessFactsResource

days = (date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19))
reader = ConfirmedBusinessFactsResource()
facts = reader.read_facts(
    subject_type="etf",
    fact_types=(FactType.FUND_LIQUIDATION_STARTED,),
    window_start=days[0],
    window_end_exclusive=days[-1] + timedelta(days=1),
)
liquidating_by_day = {
    day: {fact.subject_key for fact in facts if fact.applies_on(day)}
    for day in days
}
```

项目已经注册了 `confirmed_business_facts`。采用 `required_resource_keys` 的检查或 sensor 把这个键加入自身的声明，再通过 `context.resources.confirmed_business_facts` 取用。下层计算接收查到的记录或代码名单。程序使用 `fact_type`、`subject_key` 和生效日期做判断，公告标题、原文和维护说明供人工查证。需要按明确代码缩小查询时，登记模块的 `find_effective_facts` 支持 `subject_keys` 参数。 [只读资源](../../orchestrator/src/orchestrator/defs/resources.py) · [查询接口](../../orchestrator/src/orchestrator/defs/confirmed_business_facts.py)

### ETF 复权因子的实际判断

先用该交易日采用的 ETF 基础信息算出可入库名单，再从「当天必须存在」的名单里扣除已进入清算的代码。多出代码检查继续按可入库名单判断，源数据一致性检查继续核对符合入库条件的 Raw 记录。

- 11 月 16 日，`530080.SH` 的 Raw 有有效复权因子 `1.0`，Silver 保留原值。
- 11 月 17 日，Raw 缺这只 ETF 的因子，覆盖检查按已生效的清算事实判定可以缺省。其他应有代码缺失时仍报错。
- 补历史日期时，使用该交易日已验收的 ETF 基础信息。11 月 18、19 日使用原日期快照，保留了 11 月 20 日才进入清算的 `159528.SZ` 的有效源记录。人工补数时在 ETF 复权因子单日任务的 `historical_basic` 配置中指定该日基础信息 Raw、Silver 的产出编号。日常任务使用执行日快照。 [人工补数配置和核验](dagster-confirmed-business-facts-low-level-design-v1.md#historical-basic-config)

## 4. 追溯、更正和撤销

打开某个交易日的 ETF 复权因子覆盖检查，查看 `goldenshare/confirmed_business_fact_versions`。其中每项含 `ts_code`、`fact_id` 和 `revision`。再用 `history --fact-id` 查对应版本的公告和维护记录。历史检查结果保存当时采用的版本。重新运行检查时使用当前仍适用于业务日期的最新事实。

发现公告日期或证据需要改正时，先查当前版本，再用 `correct` 提交完整的新日期区间、理由和证据。需要撤回这件事时用 `revoke` 写明理由。两者使用原事实编号追加版本。ETF 代码或事实类型填错时，先撤销，再按正确对象另行登记。下面命令使用占位变量；执行前从查询结果及已批准证据取值。

```sh
.venv/bin/python3 -B -m orchestrator.defs.confirmed_business_facts_cli correct \
  --fact-id "$DG_FACT_ID" --expected-revision "$DG_FACT_CURRENT_REVISION" \
  --effective-from "$DG_FACT_EFFECTIVE_FROM" --reason "$DG_FACT_CORRECTION_REASON" \
  --evidence "$DG_FACT_PUBLISHER" "$DG_FACT_EVIDENCE_URL"

.venv/bin/python3 -B -m orchestrator.defs.confirmed_business_facts_cli revoke \
  --fact-id "$DG_FACT_ID" --expected-revision "$DG_FACT_CURRENT_REVISION" \
  --reason "$DG_FACT_REVOCATION_REASON"
```

更正示例的结束日期为空。如新版本有结束日期，另加 `--effective-until`。提交中断后先查历史，按当前结果决定是否重做。同样的登记或同样的更正已生效时会回显已有版本。遇到日期重叠或版本已被他人更新时，核对最新记录后再提交。

覆盖检查成功读表且当日没有适用事实时，记录空的版本列表。读库失败时，覆盖检查报「读取已确认业务事实失败」，sensor 记录受阻日期。核对只读连接、权限和登记库可用状态后重试该日。 [正式检查的版本和错误记录](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py) · [sensor 文件核验](../../orchestrator/src/orchestrator/defs/asset_guards/etf_daily_lake_readiness.py)

## 5. 接入验收清单

- [ ] 说明读哪个对象、哪些事实和哪些日期，并写清该数据集如何使用它。未接入的任务用各自的来源完成。
- [ ] 用独立样本验证生效前、当天、结束日三个边界。正常读取无适用事实时按原业务规则处理。
- [ ] 分别验证允许缺省、源端有效记录保留、其他对象真缺数、Silver 漏写有效数据，以及多出不符合入库条件的代码。
- [ ] 手动检查与日常文件核验对同一天给出一致的结果。重跑能读回实际使用的事实编号和版本。
- [ ] 更正、撤销后，新运行按当前事实判断，旧结果仍能追到历史版本。登记库不可读时，受影响任务说明原因和日期。
- [ ] 正式验收后读回文件、检查记录和实际使用的输入。人工补数应核对 sensor 是否已恢复原状态。 [ETF 首次接入的正式验收](dagster-confirmed-business-facts-low-level-design-v1.md#formal-recovery-results)
