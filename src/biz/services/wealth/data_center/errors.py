"""One public error adapter, preserving private safe reason codes underneath."""
from datetime import date

class DataCenterError(Exception):
    def __init__(self,code,message,status=503):
        self.code,self.message,self.status=code,message,status
        super().__init__(code)


def mapped_error(reason):
    if reason.startswith(('archive_database','archive_schema','archive_import','archive_not_found')):
        return DataCenterError('DC_LEDGER_FAILED','本地公告台账暂不可读取')
    if reason.startswith('source_day_missing:'):
        missing=reason.removeprefix('source_day_missing:')
        try:
            if date.fromisoformat(missing).isoformat()==missing:
                return DataCenterError('DC_SOURCE_UNAVAILABLE',f'本地尚未同步 {missing} 的公告数据，请调整查询日期或等待同步后刷新列表')
        except ValueError:
            pass
    if reason=='insufficient_disk_space':
        return DataCenterError('DC_SPACE_INSUFFICIENT','本地磁盘空间不足，请处理后重新查询')
    if reason=='query_context_changed':
        return DataCenterError('DC_QUERY_CONTEXT_CHANGED','查询依据已变化，请刷新列表',409)
    if reason.startswith(('source_file_schema','source_record','source_partition','source_row_count','source_duplicate','source_file_changed','source_footer')):
        return DataCenterError('DC_SOURCE_CONTRACT_MISMATCH','本地公告来源校验未通过')
    if reason in {'source_pypinyin_required','source_duckdb_required'}:
        return DataCenterError('DC_DEPENDENCY_UNAVAILABLE','本地公告能力缺少必需依赖')
    if reason.startswith(('source_','volume_','external_')):
        return DataCenterError('DC_SOURCE_UNAVAILABLE','所需本地公告数据尚不可读取')
    if reason.startswith(('archive_','unsafe_','non_regular','symlink_')):
        return DataCenterError('DC_STATUS_UNAVAILABLE','文件下载状态暂无法核验')
    return DataCenterError('DC_QUERY_FAILED','本地公告查询准备失败，请重新查询')


def mapped_download_error(reason):
    if reason in {'preview_stale','preview_empty'}:return DataCenterError('DC_PREVIEW_STALE','预览依据已失效，请重新预览',409)
    if reason in {'run_not_found','preview_not_found'}:return DataCenterError('DC_OBJECT_NOT_FOUND','公告预览或任务不存在',404)
    if reason in {'command_payload_conflict','run_not_recoverable','retry_scope_invalid','recheck_scope_invalid','command_invalid'}:return DataCenterError('DC_STATE_CONFLICT','当前状态不支持本次操作，请刷新后重试',409)
    if reason=='archive_already_running':return DataCenterError('DC_ARCHIVE_BUSY','同一归档已有执行，请查看当前任务',409)
    if reason in {'http_403','challenge_page'}:return DataCenterError('DC_REMOTE_BLOCKED','源站拒绝请求或要求验证，请稍后检查来源')
    if reason=='insufficient_disk_space':return DataCenterError('DC_SPACE_INSUFFICIENT','归档磁盘空间不足，请处理后重新检查')
    if reason.startswith(('archive_schema','archive_ledger','archive_binding','archive_control','command_acceptance','archive_execution','process_exit')):return DataCenterError('DC_LEDGER_FAILED','台账或执行控制暂不可用，请保留文件并重新读取状态')
    if reason.startswith(('volume_','external_','mount_','symlink_','unsafe_','non_regular','archive_device','archive_file','lake_','cross_device')) or reason in {'physical_store_unknown','disk_image_forbidden','macOS_required','multiple_hardlinks_forbidden','archive_identity_mismatch'}:return DataCenterError('DC_VOLUME_UNAVAILABLE','归档磁盘不可安全使用，请处理后重新检查')
    if reason.startswith('source_'):return mapped_error(reason)
    if reason.startswith(('catalog_','query_')):return mapped_error(reason)
    messages={
        'invalid_url':'公告链接无效', 'invalid_title':'公告标题不能用于归档文件名',
        'invalid_ann_date':'公告日期无效', 'invalid_ts_code':'公告代码无效',
        'network_or_timeout':'网络异常或请求超时', 'file_too_large':'文件超过下载大小上限',
        'html_instead_of_pdf':'源站返回网页，未返回 PDF',
        'invalid_pdf_header':'文件缺少有效 PDF 开头', 'invalid_pdf_tail':'文件缺少完整 PDF 结束标记',
        'prepared_evidence_mismatch':'待归档文件与校验凭据不一致',
        'final_path_occupied':'目标文件位置已被占用', 'filename_collision':'文件名发生冲突',
        'unexpected_content_encoding':'源站返回不支持的内容编码',
        'invalid_content_length':'源站返回的文件长度无效',
        'redirect_loop':'源站链接循环跳转', 'redirect_limit':'源站链接跳转次数超过上限',
        'redirect_missing_location':'源站跳转缺少目标地址',
        'https_downgrade_forbidden':'源站跳转未通过安全检查',
        'invalid_http_response':'源站返回异常响应',
    }
    message=messages.get(reason)
    if reason.startswith('http_') and reason[5:].isdigit():message='源站返回 HTTP '+reason[5:]
    return DataCenterError('DC_FILE_FAILED',(message+'，可重试') if message else '该文件处理失败，可查看原任务失败项并重试')
