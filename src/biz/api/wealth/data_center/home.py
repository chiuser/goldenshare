from fastapi import APIRouter
from src.foundation.config.announcement_archive import announcements_enabled
from src.foundation.config.data_audit import data_audit_enabled
from src.foundation.config.settings import get_settings

router=APIRouter(prefix='/wealth/data-center',tags=['wealth-data-center'])


@router.get('/modules')
def modules():
    cards=[]
    settings = get_settings()
    if announcements_enabled(settings):
        cards.append(dict(moduleKey='announcements',title='上市公司公告',description='查询公告与管理本地归档',
                          path='/wealth/data-center/announcements',badge='本地'))
    if data_audit_enabled(settings):
        cards.append(dict(moduleKey="data-audit", title="数据审计", description="查看本地 DG 数据更新与齐备状态",
                          path="/wealth/data-center/data-audit", badge="本地"))
    return dict(modules=cards)
