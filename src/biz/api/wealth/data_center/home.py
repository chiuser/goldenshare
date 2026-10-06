from fastapi import APIRouter
from src.foundation.config.announcement_archive import announcements_enabled
from src.foundation.config.settings import get_settings

router=APIRouter(prefix='/wealth/data-center',tags=['wealth-data-center'])


@router.get('/modules')
def modules():
    cards=[]
    if announcements_enabled(get_settings()):
        cards.append(dict(moduleKey='announcements',title='上市公司公告',description='查询公告与管理本地归档',
                          path='/wealth/data-center/announcements',badge='本地'))
    return dict(modules=cards)
