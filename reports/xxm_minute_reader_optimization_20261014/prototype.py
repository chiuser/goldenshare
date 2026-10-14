"""Research-only metadata traversal; no product imports and no source writes."""
import os,stat
from datetime import date
from src.foundation.clients.local_lake import major_index_mins_reader as m


def scan(lake_root,*,dataset,freq,start_date,end_date,cursor,stats=None):
    try:frequency_root=m.major_index_minute_frequency_root(lake_root,dataset,freq)
    except ValueError as exc:raise m.IndexMinuteRequestError(str(exc)) from exc
    if not frequency_root.is_dir():return ()
    root=lake_root.expanduser().resolve();dataset_root=frequency_root.parent.resolve()
    cursor_date=date.fromisoformat(cursor['beforeTradeDate']) if cursor is not None else None
    blocked=m._contains_symlink(frequency_root,stop=root);parts=[]
    with os.scandir(frequency_root) as directories:
        for directory in directories:
            match=m.TRADE_DATE_PARTITION_PATTERN.fullmatch(directory.name)
            if match is None:continue
            day=date.fromisoformat(match.group(1))
            if start_date is not None and day<start_date or end_date is not None and day>end_date or cursor_date is not None and day>cursor_date:continue
            candidate=frequency_root/directory.name/'part-000.parquet'
            try:info=os.stat(candidate,follow_symlinks=False)
            except (FileNotFoundError,NotADirectoryError):continue
            if blocked or directory.is_symlink() or stat.S_ISLNK(info.st_mode):
                raise m.IndexMinuteSourceContractError('指数分钟分区不得使用符号链接。')
            if not candidate.is_relative_to(root) or not candidate.is_relative_to(dataset_root):
                raise m.IndexMinuteSourceContractError('指数分钟分区路径越界。')
            if not stat.S_ISREG(info.st_mode):continue
            parts.append(m._PartitionFile(trade_date=day,path=candidate))
            if stats is not None:stats[candidate]=info
    parts.sort(key=lambda p:p.trade_date,reverse=True)
    return tuple(parts)


class FastReader(m.MajorIndexMinsLakeReader):
    def history_source_signature(self,request,*,dataset):
        normalized,_=m._normalize_request(request,dataset=dataset)
        if normalized.cursor is not None:raise m.IndexMinuteRequestError('完整历史读取不接受 cursor。')
        infos={};parts=scan(self._lake_root,dataset=dataset,freq=normalized.freq,start_date=normalized.start_date,end_date=normalized.end_date,cursor=None,stats=infos)
        if len(parts)>m.MAX_INDEX_MINUTE_PARTITION_FILES:raise m.IndexMinuteHistoryBudgetError('完整历史超过分区预算。')
        self._prepared_history_partitions[(dataset,normalized.freq,normalized.start_date,normalized.end_date)]=parts
        while len(self._prepared_history_partitions)>2:self._prepared_history_partitions.pop(next(iter(self._prepared_history_partitions)))
        return tuple((p.trade_date.isoformat(),str(p.path),infos[p.path].st_dev,infos[p.path].st_ino,infos[p.path].st_size,infos[p.path].st_mtime_ns,infos[p.path].st_ctime_ns) for p in parts)
