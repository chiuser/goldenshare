# 数据中心公告 DC1 实施验收（2026-10-06）

状态：**DC1共用核心、schema3与CLI消费者迁移完成；隔离验收通过，尚未提交。** 依据[技术方案](../wealth/docs/pages/data-center/data-center-announcements-implementation-design-v1.md)和[LLD](../wealth/docs/pages/data-center/data-center-announcements-low-level-design-v1.md)；用户已确认DC1与本地pypinyin依赖，未授权正式台账迁移、正式索引或真实下载。逐文件指纹及数量见[机器报告](wealth_data_center_dc1_acceptance_20261006.json)。

## 实现与边界

原脚本主实现移到Foundation clients/announcement_archive，SQLite访问移到Foundation DAO；执行循环和单文件修复由Ops runtime负责。文件核验在Files基础能力，DAO maintenance仅负责有界查询。原两个CLI路径、参数、输出结构和退出码保留；schema输出随台账升级反映3。原实现包和旧import清零，没有转发兼容层。core.py和source.py与提交前内容逐字节相同，六字段、身份算法、逐日读取及DG消费者合同没有改变。

schema1/2写入口在调用方持有本机execution.lock和外盘archive.lock时，以单SQLite事务升级到3；schema1中间DDL不可独立提交。只读CLI识别1/2/3，不创建或升级。保留旧字段、来源映射、路径、结果、尝试次数和冷却；新增run会话、尝试、控制slot、命令回执及网页所需字段。schema按允许列、主键和索引校验，未知/损坏版本阻断，不清空或重建。

本机锁先于外盘写探针/归档锁取得，防止外盘锁文件inode替换后出现双执行；同owner不能接纳第二活动run，终态释放持久slot。DAO接纳/孤儿恢复要求调用方已经持有双锁，不能把直接打开SQLite当作接纳授权。旧未结束运行在显式新命令中记interrupted，不自动执行HTTP。run结果幂等且已完成结果不可改写；单文件观察写失败保留已提升PDF，重放可以零请求补记。未完成尝试保留为中断证据。

公共HTTP transport逐次解析并检查全部DNS地址，连接绑定已核验的数字IP，同时保留原Host/TLS名称；禁用连接复用和隐式代理。私网、loopback、linklocal、保留/组播及携私网地址的IPv6转换形式被拒绝。DNS调用等待受connect预算及取消约束；DNS卡住后阻断run，等待线程不继续建立连接。重定向仍经过同一Limiter和目标校验。仅测试显式注入的HTTP客户端可访问临时本机fixture，产品无绕过开关。

## 硬口径对账

| DC1要求 | 实现与证据 |
| --- | --- |
| 单一核心与消费者一起迁移 | clients/DAO/Ops、两CLI、三个原专项及process/schema fixture；旧包删除、旧import清零、架构护栏 |
| 身份/路径/限速及CLI保留 | core/source逐字节不变；原专项覆盖日期、缺值、无URL、碰撞、删除后恢复、取消续跑、重放 |
| 原子升级、严格识别、旧事实保留 | 新runtime专项覆盖1/2→3每个旧列、失败完整回滚、1/2/3只读字节不变、重复打开及未知/损坏拒绝 |
| 锁/slot/退出/冷却 | 外盘锁inode替换、本机锁实际子进程退出、同owner接纳拒绝、会话终态、429期限、SIGINT/实际进程退出及prepared/rename窗口 |
| 历史不改写、观察不回滚文件 | 幂等结果、禁止改写已完成outcome、finish_attempt写失败后PDF保留且重放零请求；修复不改历史结果 |
| 封存前零HTTP、批500及稳定代表标题 | 原DG日对账专项；取消前不领新任务；跨批次/倒序同URL标题选择一致、已有title/path不重命名 |
| DNS绑定与目标限制 | public域名模拟、IPv4/IPv6、混合DNS拒绝、仅一次查名、Host/SNI保留、重定向私网拒绝、DNS超时/取消 |
| 依赖和目录权限 | 仅安装pypinyin0.55.0，local-lake固定版本、Python3.13.5五名称样本通过；新台账/锁0600、归档本机状态目录0700 |

完整回归387项通过（20.07秒），最终按目录职责移位后受影响的公告与架构217项复测通过（19.77秒）。Foundation规定的definition/resolver/runtime registry门禁在完整回归内通过；ingestion-lint-definitions、compileall及两个CLI --help通过。未运行不存在的页面/API测试。pypinyin依赖测试在未安装可选组的环境可跳过，本机验收未跳过。

CodeGraph开发前explore/impact核对原CLI、source_projection、Ledger/Source/HTTP/File、维护与测试消费者；同名Ledger/execute噪声用实际源码/SQL补充。开发后sync/status为up to date，并复核迁移后身份调用路径。依赖矩阵不改：Foundation只依赖自身，Ops只依赖Foundation/Ops，scripts只作为入口；新增/恢复主实现均不进入legacy。后续Biz/App端口和鉴权装配仍待DC3/DC4，不在本次验收内。

## 正式来源最小只读证据

通过迁移后的真实Source读取2026-07-26：5条记录、5个文件身份、footer=5，文件1807字节，读取1.211秒。SHA256为83562daeb1e87b11dd70ab4dd3985df818ce7c411ff1fbf67bb3a86788330104，与10月5日报告一致。没有打开下载台账、请求PDF或写入来源。该样本证明迁移后的读者和身份投影仍可使用正式源，不证明全历史容量、下载网络或DG持续更新已验收。

## 下一步与未执行项

DC2实现按日期可重建的公告索引、公司/别名/首字母搜索、六列查询及先筛选后分页的存在性快照。网页后台预览/继续/精确失败重试/进度属于DC3，页面属于DC4，正式最小运行属于DC5。schema3中预留字段/表不代表这些网页功能已经实现。

本轮没有正式归档台账迁移、正式查询索引、远程PDF、Prod/Lake写入、DG动作、前端/API改动或提交。真实拔盘、多域名/大文件和网页容量预算留到对应阶段；不得据此直接启动全量下载。
