# 本机 DG 统一启动方案 v1

状态：实现及隔离/真实只读检查完成；真实冷启动未执行，2026-10-05。用户要求依赖未启动时自动启动本机 PG、CH，并完成此前 Prod CH 隧道前置检查。新增入口不改变手工 dg dev、现有资源、资产合同或调度状态。

## 1. 行为和范围

入口为 `lake_console/bin/lake-dg-start`。通过 Bash 登录环境读取现有 `~/.bash_profile`；参数传给本项目现有 Python，不执行 uv sync、安装、更新或数据库初始化。正常执行自动补齐依赖并启动 DG；`--check-only` 只检查，不启动服务、创建目录或写实例状态。重复启动检查在任何服务启动前执行。

顺序：环境与配置 → 启动互斥/3000占用 → 本机PG → 本机CH → Prod CH隧道 → 外盘提示 → exec本项目dg dev。每项连接均为有超时的真实查询，不把TCP监听当成健康。只有端口未监听才允许启动一次；端口已监听但认证/查询失败则阻断，不重启、不杀已有进程。全部阻断项通过才启动DG。

PG复用已安装Homebrew postgresql@18（本机实查服务进程760），数据目录/opt/homebrew/var/postgresql@18、PG_VERSION=18。只执行已有brew services start，不initdb、建库、迁移、创建账号或安装。CH复用lake-clickhouse-start；只支持该脚本维护的127.0.0.1:9000。Prod CH复用lake-prod-clickhouse-tunnel，自动调用新增--batch模式，禁止交互密码与host-key提示，未知host key/认证错误会明确失败；不改known_hosts或SSH配置。隧道启动后必须通过Prod CH身份执行SELECT 1。

启动前后保持PG/CH和隧道运行，不随DG退出而停止，已存在的服务不被接管；启动失败仅终止本轮新建且尚未通过健康验证的隧道进程。Ctrl-C在等待阶段同样清理该未验证隧道。启动DG后依赖继续独立运行。DG启动互斥锁由DG入口进程保留，锁文件不参与数据事实。

外盘仅警告，遵守LakeRootResource不阻断dg dev的现行规则：只读检查/Volumes/datasource挂载、正式raw/silver/gold/staging目录及DuckDB临时目录、空间，不创建目录、不写探针。正式运行时原有健康检查和写湖门禁继续生效，不以本入口健康结果替代。

TUSHARE_TOKEN / GOLDENSHARE_FEISHU_WEBHOOK_URL缺配置仅警告，不发源请求或通知。Prod PostgreSQL独立资源、本机lake_meta及所有业务数据集不作本入口强制探测；本轮保障DG控制库、本机CH与Prod CH这一明确启动链，不承诺所有外部服务健康。

## 2. 配置项审计

| 配置/策略 | 默认及来源/持久化 | 消费者与生效/可见性 |
|---|---|---|
| DAGSTER_HOME | 现有env，缺省~/.goldenshare/dagster_home；只允许本机正式目录 | launcher读取已有dagster.yaml；展示路径；不创建实例 |
| PG连接 | 现有storage.postgres.postgres_url，支持字符串或env引用 | 只读探测，连接超时3秒、SQL3秒；不展示URL/密码；DG读取同一配置 |
| 本机CH连接 | 现有CLICKHOUSE_HOST/PORT/USER/PASSWORD/DATABASE | launcher与ClickhouseResource共用env；password可为空；非loopback或非9000拒绝自动启动 |
| Prod CH连接 | 现有PROD_CLICKHOUSE_HOST/PORT/USER/PASSWORD/DATABASE | 真实只读探测；只允许loopback隧道；port传给既有PROD_CLICKHOUSE_TUNNEL_PORT，不额外保存 |
| SSH目标 | 既有PROD_CLICKHOUSE_SSH_HOST，默认goldenshare-prod | 隧道脚本；新--batch只控制BatchMode/ConnectTimeout，不更改手工默认 |
| DG host/port/pool/poll | 固定127.0.0.1/3000/80/10000，沿用当前运行命令 | 集中StartupPolicy，单消费者launcher；暂无新env/用户调参 |
| 等待预算 | 查询子进程10秒、单依赖等待30秒、服务启动命令40秒、轮询1秒 | 集中StartupPolicy；每阶段打印进度；异常只显示分类和退出码，避免泄密 |
| 启动锁/隧道日志 | 正式DAGSTER_HOME/lake-dg-start.lock及~/.goldenshare/dagster_logs/lake-dg-start-tunnel.log | 仅正常启动创建；check-only零创建；锁继承到DG主进程，日志追加 |
| Lake路径/空间 | 复用paths.DEFAULT_LAKE_ROOT、DEFAULT_LAKE_STAGING_ROOT及health既有64GiB门槛 | 只读提示，导入消费者核验后复用；不新增另一份Lake配置 |

所有值每次启动读取；不增加Settings/DB配置表、不保存秘密。禁止打印底层驱动异常正文、带密码argv或完整env。探测子进程只从stdin接收连接配置。

## 3. 影响与性能

CodeGraph explore核对defs装配、LakeRootResource与ProdPostgresResource及消费者，补读既有bin脚本、资源env、PG实际进程、现有PG18目录和dagster.yaml形状。启动代码放orchestrator/local_startup.py，位于defs外，不被自动扫描成资产。shell为入口，不恢复旧Console；无需src.foundation/ops/biz/app或qtf依赖。CodeGraph不能证明外部服务状态，真实只读探测补充证据。

每轮最多3连接检查（PG含控制表存在性检查）、每个缺失依赖最多启动一次；无业务表扫描、无Tushare配额、无Lake业务写入；失败等待有上界。PG/CH共享服务不为测试停机；当前DG正在运行，本轮不重启DG、不执行正式job验收。

## 4. 验收门禁

隔离测试覆盖：就绪不启动；未监听自动启动一次并查询读回；check-only不启动/建目录；认证/占用/未知配置不启动；启动失败和等待超时阻断DG；PG18目录缺失拒绝初始化；隧道失败/取消仅清理新未验证进程；重复启动锁/端口；秘密不输出；正常exec参数和环境沿用；挂载问题警告不阻断。

真实只读check-only按现有环境核验三连接及配置；不停止现有PG/CH来制造故障，不把替身测试说成真实冷启动。bash -n、scoped Ruff、文档检查和diff检查必跑。交付记录静态、隔离与真实证据各自范围。

## 5. 实现与验收（2026-10-05）

[验收与逐条对账](../../reports/dg_local_startup_20261005.md)。统一入口、外部依赖真实查询、缺失自动启动、防重复、取消/超时及不接管共享依赖已落地；32项隔离检查、Ruff和Bash语法检查通过。真实check-only以现有PG/CH/Prod CH身份退出0，约0.831秒，不启动或写入服务/实例/业务数据。现有DG及共享依赖未为测试停止，真实冷启动未执行；该限制明确保留。没有修改源码调度默认值或实例开关。
