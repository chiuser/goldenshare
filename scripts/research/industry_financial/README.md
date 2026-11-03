# A股行业财报研究计算

当前正式交付：[完整独立HTML报告](../../../reports/A股行业研究报告_2026年前三季度.html)。已合入三批内容，可离线打开；中间展示清理及底稿目录说明见[报告目录](../../../reports/a_share_industry_prosperity_2026q3/README.md)。以下命令及阶段记录保留原执行含义。

依据两份原研究文档 `docs/product/a-share-industry-prosperity-2026q3-*v1.md`。试算（五行业100家）及正式范围（当前5,571候选）共用公式、季度差分、Q4冲突、湖北宜化重述边界及四维七项；旧九图仅作历史追溯。新版按已认可样章和原计算口径§10.11—10.15制作，执行范围单独冻结，不开放研究参数。

在仓库根使用现有环境：

```bash
.venv/bin/python -m scripts.research.industry_financial.run --help
.venv/bin/python -m pytest scripts/research/industry_financial/tests -q
```

默认 `--scope trial`，输出必须为 `reports/a_share_industry_prosperity_2026q3/trial_日期_序号`。正式范围显式 `--scope formal`，目录前缀为 `formal_`，全范围生产读取必须有专项批准。当前运行的批准保存在自身evidence/authorization.json。已有目录必须 `--resume`；`--stop-after 20`只用于已设计的受控中断；`--extract-only`停在冻结输入；`--resume --offline`只重算本地输入，不能证明源仍一致。

formal.py按现有psql-remote.sh只读入口读取151批：身份3、树1、成员12、估值3、财务132。各批≤批准上限，完成回执/哈希独立持久化，逻辑报告期在全部批次完整后发布索引。CANCEL文件、进程退出或状态保存失败不删除完整输入；恢复核哈希与源指纹，变更即停止。源指纹不能证明原子跨表快照。不得解除既有范围或资源限制。

完整运行还需已有三份公告核验、质量边界、render_environment.json及report_environment.json；缺证据即停，不自动认证或安装依赖。后者只定位已安装Node、Data插件及本主题/private/tmp下报告临时工程，不是研究参数。report.py保存冻结快照、CSV和报告正文，report_app内自有正文与样式文件负责报告呈现。运行时只复制到临时工程的允许编辑内容；使用既有Data公共组件，保护来源、编辑和导出，不复制整套基础设施进仓库，不安装包。

计算完成不自动等于报告验收：还需validate_formal、validate_report_snapshot及实际浏览器核验；报告最终buildStatus应为complete。真实财务/估值语义、取消—恢复、上下级金额、同分并列、金融排除、坐标/显示单位及原输入哈希均分别留证。最后源核验与正式计算输入保持区分。

原正式计算交付见 `reports/a_share_industry_prosperity_2026q3/formal_20261101_01/README.md`；新版第一批见 `reports/a_share_industry_prosperity_2026q3/narrative_20261103_01/README.md`。不写Prod/Lake，不改源数据、不提交或发布，不自动交易。报告是当前公司范围的条件研究，未验收全部历史重述或投资收益。

两个图表样章入口（仅使用已有冻结汇总，不连接数据源）：

```bash
.venv/bin/python -m scripts.research.industry_financial.sample_chapters --output reports/a_share_industry_prosperity_2026q3/chapter_samples_日期_序号
.venv/bin/python -m scripts.research.industry_financial.sample_chapters --output reports/a_share_industry_prosperity_2026q3/chapter_samples_日期_序号 --build
```

新目录才允许生成数据；已存在目录只能在源哈希及Spec一致时执行构建，最终带`--complete`清除创建状态。维护内容位于sample_report_app，输出与精确核验分开。当前两个样章见chapter_samples_20261102_01/report.html；旧完整报告未被覆盖。原九图不再作为新版报告的呈现约束。

新版第一批当前财务入口（只复用本地冻结证据，不能用于启动第二批）：

```bash
.venv/bin/python -m scripts.research.industry_financial.publication --output reports/a_share_industry_prosperity_2026q3/narrative_日期_序号
.venv/bin/python -m scripts.research.industry_financial.publication --output reports/a_share_industry_prosperity_2026q3/narrative_日期_序号 --resume
.venv/bin/python -m scripts.research.industry_financial.publication --output reports/a_share_industry_prosperity_2026q3/narrative_日期_序号 --build --complete
```

新目录按一级行业逐个提交，已存在目录显式`--resume`并核对来源、代码及配置；完成单元不重写。`CANCEL`文件仅中断该目录正在执行的本地生成。构建复用已认可样章作者项目与稳定app ID，每目录最多3轮；narrative_20261103_01已用完3轮，不重复构建。维护展示仍在report_app，不修改原核心12个计算文件。第一批49图、31一级/128二级状态、金融120家公司两期比较已验收，历史与预测章节尚未进入。

管理员五项反馈的修订入口复用已完成快照与单元，不重复取数、金融投影或旧指标计算：

```bash
.venv/bin/python -m scripts.research.industry_financial.publication --output reports/a_share_industry_prosperity_2026q3/narrative_新日期_序号 --revise-from reports/a_share_industry_prosperity_2026q3/narrative_20261103_01
```

第一批历史修订见narrative_20261103_02/README.md（重复HTML已清理）：59幅图，增加应收余额变动、前三大公司名称、比例%标签及标题调整。44项测试和桌面/手机验收通过，原01证据不覆盖；本目录也已用完3轮构建，不重复运行。--revise-from只准备新目录，构建仍独立执行--build --complete；生成恢复需显式--resume。完整行为与预算见原计算口径§10.13，原始第一批入口保留历史生成用途。


第二批历史入口（§10.14，仍只读已有冻结收入）：

```bash
.venv/bin/python -m scripts.research.industry_financial.publication --output reports/a_share_industry_prosperity_2026q3/narrative_新日期_序号 --history-from reports/a_share_industry_prosperity_2026q3/narrative_20261103_02
```

生成恢复用同一命令加`--resume`，构建另用`--build --complete`。history_publication复用原Book和PublicationRun，三年9M与11期公司范围分别固定；金融只用三年营业总收入/P，不新增金融季度。最新合并报告narrative_20261103_03已完成，60项测试及真实来源/父子/年度对账、取消恢复和桌面/390px检查通过。该目录3轮构建已用完，不再构建；需要另次修订先按原文档设计新目录，不覆盖旧产物。报告、原生来源及本文前述旧运行记录保留；预测及总结仍待第三批。


第三批全年预测、投资价值及总结入口（只读冻结结果，不重新拟合或评分）：

```bash
.venv/bin/python -m scripts.research.industry_financial.publication --output reports/a_share_industry_prosperity_2026q3/narrative_新日期_序号 --forecast-from reports/a_share_industry_prosperity_2026q3/narrative_20261103_03
```

恢复同一命令加`--resume`，构建另用`--build --complete`。forecast_publication复用PublicationRun及源验证，只投影groups/ranking/sensitivity；模型/评分的公司范围、原名次及并列保留。最新完整报告为narrative_20261103_04，300图、74项主题测试、真实取消恢复及桌面/手机检查通过，详见其README和原计算口径§10.15.1。本目录3轮构建已用尽，不再构建；源、代码或配置变化不能强行续跑，应按原设计明确新修订目录。原核心12文件、旧报告与数据保持只读，无Prod/Lake写入或提交发布。
