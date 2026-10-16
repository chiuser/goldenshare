# B组 H1—S2—E1 内核升级执行记录

依据：LLD §17；2026-10-16 用户确认按详细方案实施。只在 dev-interface 当前工作区推进。

| 硬口径 | 代码落点 | 验证 | 状态 |
| --- | --- | --- | --- |
| B01 唯一内核及固定新Spec；普通、TOP不变 | spec/types/calculator | 冻结普通/TOP回归、新95事件 | 已通过 |
| B02 原负段低点冻结、离段后严格跌破、DIF/新信号优先、无TTL | calculator底部后处理 | T01—T04 正反例 | 已通过 |
| B03 单pending快照、原子严格恢复 | snapshot/restore/calculator_at | T05—T07 前缀/污染反例 | 已通过 |
| B04 独立账本、过去投影、窗口关联闭合 | query/DTO | T08—T10 API合同/缓存 | 已通过 |
| B05 预测数学/筛选不变、克隆隔离 | 原forecast消费者 | T11—T12 356个冻结预测 | 已通过 |
| B06 四周期图表与详情消费新合同 | TS types/adapter/UI | T13—T15 adapter/geometry/hook | 已通过 |
| B07 完整来源、4秒/200ms/缓存预算不扩大 | 原读取/运行时及验收入口 | T16 冷暖/整页/双标签 | 已通过 |
| B08 原证据不覆盖；A组及顶部疑报不修 | 所有改动范围 | SHA保护及逐项对账 | 已通过 |

CodeGraph：codegraph_explore(XxmCalculator)、codegraph_impact(XxmCalculator, depth=2)，核验识别查询、DTO、预测恢复及Wealth两个图表消费者。边界保持Biz→Foundation、Wealth→HTTP；无新配置、SQL、依赖或数据写入。页面由用户验收。


最终对账：B01—B08均完成技术门禁，页面待用户验收，不代验、不提交／部署。源／普通／TOP／预测及所有预算保持，没有方案冲突或未经确认的扩围。两次脚本错误均保留失败证据，纠正验收参数／路径后新批次完整通过。

| 测试组 | 代码／实际测试与证据 | 结果 |
| --- | --- | --- |
| T01—T04 | calculator.py的独立底部后处理；test_xxm_calculator新增冻结低点、变色、等号、DIF／接替优先、原段／零柱、40柱无TTL、TOP事件共存；完整旧点序列／事件／TOP及B1新增逐项核对 | 通过 |
| T05—T07 | spec.py／snapshot／restore；同文件缺字段／错身份／未来／错误ID／原子失败／合法回退；API calculator_at、原999／1000／1001与来源修订；增量旧容器／嵌套参照／checkpoint隔离 | 通过 |
| T08—T10 | query底部投影／窗口选择与严格DTO；test_wealth_index_detail_xxm_api四周期四过去时点、单柱外部结构、未来隐藏、老point合法pending、空窗、版本／双向／孤儿／缺字段反例；原20点四周期测试保留 | 通过 |
| T11—T12 | 唯一forecast clone／calculator_at消费者，356组完整数学及文案一致；18个日线校准失败保持；clone父状态隔离；真实API新detectorSpecHash及原v0.2 | 通过 |
| T13—T14 | TS adapter及UI四周期新底部详情／marker，全部point先验证；旧版／缺字段／未来／错方向／双关联／孤儿／结束前point反例 | 通过 |
| T15 | 原geometry／client测试及hook旧版失败后h1重试；两图表共享签名／primitive保持；前端全量1179项和类型／构建 | 通过 |
| T16 | 新runner frozen／api／budget三模式；既有mixed入口306实际请求；正常源与冻结重叠／130份原SHA；所有新证据独立OUT | 通过 |

CodeGraph变更后已sync／status确认当前根索引。未修改读取／运行时／预测数学及路由，43份已审计代码保持原SHA；变更现有19份（含测试及研究README），新增1份dev-only runner，另同步四份原方案。完整路径与最终SHA见manifest。
