"""One public error adapter, preserving private safe reason codes underneath."""
class DataCenterError(Exception):
    def __init__(self,code,message,status=503):
        self.code,self.message,self.status=code,message,status
        super().__init__(code)


def mapped_error(reason):
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
    return DataCenterError('DC_INDEX_FAILED','本地公告查询准备失败，请重新查询')
