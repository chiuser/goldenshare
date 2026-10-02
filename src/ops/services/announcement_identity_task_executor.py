"""Maintenance adapter: business migration owns commits; Ops owns observations."""
from src.foundation.datasets.anns_d_contracts import digest
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.services.migration.announcement_identity import AnnouncementIdentityMigration
from src.ops.runtime.maintenance_executor import MaintenanceExecutionPlan, MaintenanceExecutionUnit, MaintenanceExecutionResult
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext

ACTION = 'maintenance.migrate_announcement_identity'


class AnnouncementIdentityTaskExecutor:
    def __init__(self, *, session_factory):
        self.session_factory = session_factory

    def plan(self, request):
        params = dict(request.params)
        if request.action_key != ACTION:
            raise ValueError('公告身份迁移动作不符')
        allowed = {'execution_mode','start_id','end_id','state_path','recovery_report_path','finalize','expected_state_digest'}
        if set(params) - allowed:
            raise ValueError('公告身份迁移存在未知参数')
        params.setdefault('execution_mode','CHECK')
        params.setdefault('finalize',False)
        if params['execution_mode'] not in {'CHECK','APPLY'}:
            raise ValueError('执行模式必须为CHECK/APPLY')
        if any(type(params.get(k)) is not int or params[k] < 1 for k in ('start_id','end_id')) or params['start_id'] > params['end_id']:
            raise ValueError('迁移主键范围无效')
        if not params.get('state_path') or type(params['finalize']) is not bool:
            raise ValueError('须指定校验文件及布尔切换意图')
        if params['execution_mode']=='APPLY' and (not params.get('recovery_report_path') or not params.get('expected_state_digest')):
            raise ValueError('APPLY须提供恢复报告和已审阅摘要')
        if params['finalize'] and params['execution_mode']!='APPLY':
            raise ValueError('CHECK不允许最终切换')
        return MaintenanceExecutionPlan(plan_hash=digest((ACTION,params)), units=(
            MaintenanceExecutionUnit(unit_key='announcement_identity',payload=params),))

    def execute_unit(self, unit):
        raise RuntimeError('公告身份迁移必须在TaskRun中执行')

    def execute_unit_for_task_run(self, unit, *, context):
        with self.session_factory() as session:
            observer = TaskRunIngestionContext(session, independent_cancel=True,
                timeout_seconds=get_dataset_definition('anns_d').storage.reconciliation_lock_timeout_seconds)
            def cancel():
                return observer.is_cancel_requested(run_id=context.task_run_id)
            checked_rows = 0
            labels = dict(checking='校验旧身份', checking_backup='核验备份', rechecking='复核冻结范围',
                          applying='更新身份', verifying='核验迁移结果', complete='完成')
            def progress(value):
                nonlocal checked_rows
                checked_rows = max(checked_rows, value.get('checked_rows',0))
                total = value.get('total',0)
                # Completed counts represent committed identities; phase distinguishes verification.
                done = value.get('completed',0) if total else 0
                observer.update_progress(run_id=context.task_run_id, unit_done=done, unit_failed=0,total=total,
                    rows_saved=value.get('completed',0),rows_fetched=checked_rows,
                    message='公告身份迁移', ingestion_diagnostics={'identity_migration':value},
                    current_object={'entity':{'name':f"公告身份迁移：{labels[value['phase']]}；ETA暂无法估算",'code':str(value.get('last_id',''))},'attributes':{'phase':value['phase'],'eta':'暂无法估算'}})
            params = dict(unit.payload)
            result = AnnouncementIdentityMigration(session.get_bind()).run(
                mode=params.pop('execution_mode'), cancel=cancel,
                progress=progress, **params)
            return MaintenanceExecutionResult(rows_fetched=result['count'],
                rows_saved=result['count'] if unit.payload['execution_mode']=='APPLY' else 0,
                summary_message='公告身份校验完成' if unit.payload['execution_mode']=='CHECK' else '公告身份迁移完成',
                metadata={'identity_migration':result})
