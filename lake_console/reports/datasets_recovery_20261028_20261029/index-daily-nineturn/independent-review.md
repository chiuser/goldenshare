# 2026-10-28主要指数日线九转两项补齐独立对账

结论：已有执行证据与原方案/LLD §18.6一致，未发现阻断收尾的问题。本次只读已有JSON和文档，不访问正式服务、数据库或Lake，不执行计算或重复审计；只新增本报告。

- [Gold验收](gold-verified.json)：原job `gold_major_index_daily_nineturn_update_job`，run `d4c794f5-4939-482e-a93c-4ba70d3eadd7`，SUCCESS，28日11行；1物化、1通过的blocking check，target_run_id及storage_id准确绑定。原六项完整性规则无失败，来源21份的身份记录与方案一致。
- [Prod观察](prod-observation.json)及[Prod验收](prod-verified.json)：原sensor自动提交run `22dbd172-3a3c-4c51-bb1f-075eb31256bf`。独立按Gold run id、28日及原批次算法核算，预期run_key为`prod_core_index_daily_nineturn_sync:gold_major_index_daily_nineturn_update:2026-10-28:f5bd8c6a84d5`，与实际完全一致；sensor名、job、日期及run id对应正确。SUCCESS，11行，1物化、1通过的blocking check准确绑定，原生读回11行，物化hash及check的expected/observed hash相等。
- [局部收尾](final.json)：Gold及Prod最终均11行；输入、相邻Gold文件身份及Prod邻日计数保持，两sensor仍RUNNING。本次未新增全目录审计。

原[10:40物理计数](../final-physical-audit.json)仍保存157项有数据、2项缺失、159项实际审计。原缺失恰为本次已验收的Gold及Prod两项，因此157＋2＝159，可据两次有先后顺序的证据说明28日159项按日审计资产均有数据；这不是12:23重新执行159项全局审计，也不代表所有历史或全部字段质量重新通过。

23/26/27日THS历史缺口未在本步处理，不能据28日两项补齐宣称这些历史缺口已经恢复。临时文件清理及README收尾由根代理另行记录，本报告不预先确认清理结果。
