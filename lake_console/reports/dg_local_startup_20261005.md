# 本机 DG 自动启动入口验收（2026-10-05）

目标：用户要求依赖未启动时由启动脚本自动启动本机PG、CH，随后启动DG，覆盖此前Prod CH隧道启动晚于DG的问题。依据[原方案](../docs/design/dagster-local-startup-plan-v1.md)和当前正式资源/实例配置。本轮完成实现、隔离测试及真实只读检查，尚未对现有共享服务做真实停机/冷启动，不替代公告正式日job验收。

## 变更与边界

新增bin/lake-dg-start、orchestrator/local_startup.py及tests/test_local_startup.py；原lake-prod-clickhouse-tunnel增加可选--batch（无参手工行为不变）。配置项在编码前已落原方案矩阵，README和Prod CH方案同步入口。无依赖安装/升级、schema/资产/资源/调度状态改动，不依赖Prod src/ops/app或qtf，不恢复旧Console/Kopia。

CodeGraph explore核对defs、LakeRootResource、ProdPostgresResource及消费者；补读真实bin脚本、PG服务和实例配置。图不能证明外部连接，以下只读运行补充。没有需要人工确认的子系统依赖方向变更。

## 硬口径对账

| 要求 | 实现 | 正/反验证 |
|---|---|---|
| PG/CH缺失自动启动一次，真实查询后启动DG | Runtime.ensure/start/launch | absent_starts_once、ready_reuses_service、main_launches_only_after_all_dependencies_ready、failure_never_launches_dg |
| 复用已有PG18，不安装/初始化 | PG_HOME/BINARY及Runtime.start | pg_starts_only_existing_version；17版本或缺目录拒绝 |
| 本机CH与Prod隧道分开处理 | Runtime.start；既有bin helper | local_ch_uses_existing_helper；new_tunnel_batch_cleanup_only_own_group |
| 监听但查询失败不得重启共享进程 | probe/ensure | listening_bad_query_is_not_restarted；failed_post_start_query_blocks |
| 超时/取消，不遗留未验证隧道 | 查询子进程/command/cleanup | probe_timeout_classified；timeout_blocks；cancel_cleans_pending_tunnel；command_timeout_terminates_only_spawned_group |
| ready依赖保留，不接管共享服务 | ensure释放pending_tunnel所有权 | ready_tunnel_not_stopped；ready_reuses_service |
| check-only零服务/实例写入 | main/prepare | check_only_no_lock_or_launch；missing_config_not_created；check_only_collects_all_failures |
| 防重复启动，保留现有参数 | main端口/文件锁；launch exec | busy_port_main_does_not_start；lock_prevents_service_start；launch_parameters_and_instance |
| 秘密不进入argv/输出 | probe stdin；safe errors | probe_password_in_stdin_only；probe_hides_driver_output；unhandled_error_does_not_print_secret |
| 外盘警告，飞书配置用真实资源变量 | Runtime.warnings | lake_warning_preserves_launch_and_uses_feishu_contract |
| 手工隧道行为保持 | helper的--batch解析 | manual_tunnel_default_unchanged_batch_noninteractive：真实Bash+替身ssh |

32项stdlib unittest在现有项目.venv执行，全部通过；所有服务/网络/启动动作均使用替身，未访问正式资源。没有借用其它数据集的测试启动器或改动其脏文件。scoped Ruff、bash -n、--help通过。

## 最小真实只读证据

命令：`bash lake_console/bin/lake-dg-start --check-only`，从仓库根执行，Bash登录环境。2026-10-05最终复查退出0、约0.831秒：

- 本机PG localhost:5432：SELECT 1及既有runs/event_logs/jobs存在性通过，只读事务、SQL3秒。
- 本机CH 127.0.0.1:9000：SELECT 1 LIMIT 1通过。
- Prod CH 127.0.0.1:19000：同一只读查询通过，证明隧道和远端身份当时可用。
- 外盘/源token/飞书正式变量无警告；最终完成，无目录/锁/实例/服务写入。

初次检查使用了错误的飞书变量名FEISHU_WEBHOOK_URL而提示缺配置；已依据notifications/feishu.py改为复用FEISHU_WEBHOOK_URL_ENV_VAR（GOLDENSHARE_FEISHU_WEBHOOK_URL），增加反例回归并完成上述复查。没有改动用户env。

CH查询采用agent-query-safety规定的LIMIT、max_execution_time及扫描/返回上限，只读且不读取业务表。没有以端口监听替代SQL查询，没有调用Tushare或发送飞书通知。

## 操作与剩余验证

启动：`bash /Users/congming/github/goldenshare/lake_console/bin/lake-dg-start`。依赖就绪后DG监听127.0.0.1:3000，pool80/poll10000沿用现有命令，锁继承到入口进程。Ctrl-C停止DG，已就绪PG/CH/隧道继续运行；当前手工DG未重启。

未停共享PG/CH或已有隧道制造故障，因此真实自动冷启动/再启尚未执行；该路径已用命令替身与状态读回覆盖。SSH密钥/known_hosts缺失会失败，不接受未知host key、不修改SSH配置。启动后连接仍可能中断，此入口不承诺运行期间自动修复。业务元数据、事件和日任务验收属于原公告专项，未因本入口通过而升级完成状态。
