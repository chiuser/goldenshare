# 数据中心 DC4 页面验收

日期：2026-10-07。依据：用户“提交DC3，然后推进DC4”、已确认产品/Figma R1、技术方案及LLD §9/§18。DC3已提交`83ffb83f`；DC4在当前dev-interface实现，尚未提交或部署。

## 交付与边界

新增`/wealth/data-center`和`/wealth/data-center/announcements?tab=query|downloads&runId=...`。复用现有登录、TopMarketBar、PageBreadcrumb、行情上下文与`--cs-*`样式；查询及下载均消费真实Biz API，没有生产mock adapter。默认30自然日、六列/50条公告、名称/代码/首字母候选、标题与状态筛选；下载只接受日期和间隔，灰色固定归档路径，预览后开始。

页面展示真实任务阶段、处理数量、文件字节、有限尝试、等待期限、业务更新与存活时间。支持确认停止、原任务继续、原失败单项/全部重试、有限检查、历史与关联批次。未知下载状态显示“—”并解释，100%且有失败仍为部分失败；无URL不计失败。没有首次单公告下载、公司下载、删除、覆盖、本地PDF服务、DG同步或自动全量下载。

新增源码位于`wealth/src/features/data-center/{api,model,ui}`、`wealth/src/pages/data-center`；修改现有WealthRouter/routerState及其测试。浏览器脚本位于`wealth/scripts/announcement-browser-{fixture.py,smoke.mjs}`。更新产品、方案、LLD、索引和CodeGraph快照。具体文件哈希、接口记录和截图索引见[机器证据](wealth_data_center_dc4_acceptance_20261007.json)。后端API、业务表、CLI和子系统依赖矩阵未修改。

## 硬口径对账

| LLD要求 | 页面落点 | 测试与真实证据 |
| --- | --- | --- |
| R01登录/部署 | WealthRouter认证、DataCenterPage capability | Web测试匿名401/Prod404；浏览器本地卡、Prod无卡；认证仅在隔离夹具替换，未验证生产登录服务 |
| R02未知状态 | QueryPanel/context错误和状态提示 | API不可用不变空模块；拔盘后原67条仍可查，状态NULL，不显示未下载；404未知run不变idle |
| R03六列/保留记录 | QueryPanel/后端QueryResult | 真Parquet67公告记录、64文件、2无URL；不同标题同URL两行、一归档；第二页17条；六个表头 |
| R04外链 | sourceLink/六列URL | 新标签noopener/noreferrer，名称公告详情；非法协议/凭据禁用测试；外站目的地隔离，无真实源站请求 |
| R05公司候选 | CompanySearch/查询controller | 300ms、键盘/失焦取消；PAYH选择完整代码后44条；非空未选拒绝查询，不默认第一项；名称/代码/历史别名语义另有后端测试 |
| R06查询/分页 | useAnnouncementQuery | 草稿/应用条件分离；刷新保持应用条件、reset默认、分页同queryId；公司+董事会21条；无结果清筛选；tab及返回/前进保留草稿 |
| R07两状态 | QueryPanel/后端presence | 恢复全部文件后已下载筛选65公告；NULL与未下载区分；删除/全范围状态过滤负例由后端回归覆盖 |
| R08日期创建 | DownloadPanel/PreviewRequest | 初始空日期/5秒；固定disabled路径无只读字样；反向日期禁用、0秒有效；实际preview POST只有日期和间隔，不带查询公司/标题 |
| R09五项预览 | DownloadPanel | 真实本地预览67记录/64文件/0复用/64待下载/2无URL，准备零HTTP；准备未知总量不画百分比；源变化/空范围拒绝由后端测试覆盖 |
| R10共享执行 | useDownloads/幂等意图 | 双击锁、未知响应保留原key人工重试；真实只创建一个原run；切页/卸载不发stop/continue；后台共享锁、CLI争锁由后端回归覆盖 |
| R11进度 | TaskProgress/useObserver | backend percent直接渲染；100%失败仍partial_failed；当前字节/未知长度/心跳/15秒标旧；慢GET无重叠、5秒超时保留事实 |
| R12限速/尝试 | TaskProgress/既有Downloader | 继承原间隔，不在页面另建下载循环；有限3次/退避/冷却由后端验证，合成台账只补视觉样本，不冒充真实限速故障 |
| R13精确重试 | RunResults/useDownloads | 原2个失败；singleFailed只1，allFailed恢复剩余1；root失败仍2，unresolved=0；实际各一个POST，无公司/日期扩展 |
| R14停止 | StopDialog/TaskProgress | Escape取消零stop；确认后停止，继续原范围；stopping禁用重复stop，即使旧actions.canStop=true |
| R15继续/中断 | useDownloads/isActive | 真停止→继续→终态；修复同run继续后未恢复观察的问题并有负例；后端中断手动继续展示，退出恢复执行证据沿用DC3 |
| R16物理成果 | 原Files执行器，页面不操作路径 | 真实隔离PDF传输与临时目录执行；不修改文件协议；正式size/hash/迁移/外盘验收留DC5 |
| R17阻断/检查 | DownloadPanel/recheckKind/canContinue | 卷检查与源站检查分开；403未通过remoteSource检查不显示继续；本地检查不能解源站锁，检查资格负例；真实检查执行由后端回归验证 |
| R18历史/结果 | HistoryPanel/RunResults | history20/files50/related20有界keyset；查看最近任务重取第一页再选；原root与重试批分别显示；原错误可展开，不改旧计数 |
| R19来源/配置 | API wrapper/clientPolicy/路由 | 请求只用公告命名空间；固定预算跨端合同测试；无新依赖、无Prod/DG fallback、无网页台账；分层4项通过 |

## Figma与桌面对照

已逐一读取R1的24个画板设计上下文/截图。沿用当前共享顶栏和面包屑：共享PageBreadcrumb最小36px且有12px下边距，高于Figma示例28px，这是现有组件基线优先；不为此修改其他一级页面。内容边距18px、面板间隔14px、圆角12px、字段42px、按钮38px、tab112×32px、表头30px、行58px、进度8px、弹窗520px。表区最高494px、独立滚动、表头固定；50条为每页数据量，不是50行全部铺满屏幕。

1600/1512/1460px面板无水平溢出；1366px遵循既有1460px终端最小宽，页面横向滚动，不改成移动布局。已查看列表、下载、停止确认、失败与阻断截图；这是状态/尺寸/文本与共享组件的对照，不宣称动态内容逐像素完全相同。原生日历的显示格式遵循浏览器语言，传输日期始终ISO。

| Figma | 实现与截图 |
| --- | --- |
| 1944:80 / 81 | 本地/Prod首页；home-local / home-prod |
| 1944:82 / 83 / 1950:1612 | 六列查询/候选/选择；query-list / company-candidates / company-selected |
| 1944:84 / 85 / 1950:1618 | 空/有效/反向下载日期；downloads-empty / downloads-valid / downloads-reversed |
| 1944:86 | 五统计预览；preview |
| 1944:87 / 88 | 准备/下载进度；visual-preparing / downloading |
| 1944:89 / 90 / 1950:1613 | 部分失败/全部失败重试/单项重试；partial-failed / visual-retry / visual-single-retry |
| 1944:91 / 92 / 1950:1617 | 停止/外盘阻断/源站拒绝；stopped / visual-volume-blocked / visual-remote-blocked |
| 1944:93 / 94 / 95 | 空/来源异常/完成；query-empty / query-source-error / single-retry-completed |
| 1950:1614 / 15 / 16 | 确认停止/停止中/中断；stop-dialog / visual-stopping / visual-interrupted |
| 1944:96 | 已确认规则总览，不是运行页面；按R01—R19对账，不新增评审管理功能 |

主流程使用真实路由、Biz Query/Service、Catalog、PreviewRuntime、Supervisor、Files和临时Parquet/SQLite；只有认证、外卷识别、顶栏行情和远程PDF传输是明确隔离输入。七个`visual-*`状态通过临时Ledger写入合成持久事实再经真实run API展示；它们只证明罕见状态显示，不能证明真实403/进程崩溃/外盘拔除执行行为。执行行为由DC3/本轮后端回归证明，正式环境仍待DC5。

## 验证与后续

- Wealth全量：156文件、1,127项通过（13.47秒）；数据中心/路由专项63项；typecheck/build通过。已有主bundle大于500KB的提示保留，本轮不做无关拆包。
- 实际Web后端：`PYTHONPATH=tests .venv/bin/python -B -m pytest -q tests/web/test_wealth_data_center_api.py tests/web/test_wealth_data_center_downloads.py`，62项通过（32.33秒）；分层矩阵4项通过。
- 浏览器14组证据、134次公告API请求、33张截图详见机器证据：67公告→64归档文件、2无URL、2失败→单项及全部失败重试后尚未解决0；仅预期未知任务404和来源错误503，无JS异常。只使用调试0秒与替代PDF传输，不能据此估算真实源站批量耗时。浏览器流程结束后最后补充的旧任务原因提示，由专项渲染负例验证并重新完成全量测试/构建。
- 未写正式DG/Prod/Lake/归档/索引，未启用开关或安装依赖，未推送/部署。临时服务由夹具退出时关闭；其他任务脏文件保留。
- 下一阶段DC5：先验证本机启用条件、正式台账迁移和查询索引，再在获准隔离归档执行最小真实源站下载—停止—继续—重试—物理对账；DG连续稳定性独立验收。DC4不包含自动全量下载授权。

## CodeGraph与人工边界

开工使用CodeGraph explore/impact覆盖WealthRouter、resolveTopMarketNavPath、共享顶栏/面包屑、wealthFetch和AuthProvider；代码核验六类既有导航消费者。开发后sync/status/query/impact已复核新增page/controller和共享解析器。动态回调边不完整，补查真实引用与浏览器API调用，不以图中的少量调用方代替全量核验。待人工执行的边界是DC5正式资源与实际源站，不存在尚未定位的代码调用方。
