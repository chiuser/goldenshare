from datetime import date,timedelta
import pytest
from scripts.research.index_market.chan.stock_random10 import validate_pair,CODES
from scripts.research.index_market.chan.minute_data import slots


def sample():
    days=[str(date(2021,9,9)+timedelta(days=i)) for i in range(251)]
    def rows(f):
        return [dict(code=CODES[0],frequency=f,exchange='SZSE',date=d,time=f'{d} {s}',open=10,high=11,low=9,close=10,vol=1,amount=10) for d in days for s in slots(f)]
    return rows(30),rows(60),days


def test_pair_projection():
    a,b,d=sample()
    validate_pair(a,b,d,CODES[0])
    assert b[0]['source_end']==1
    assert b[-1]['source_end']==len(a)-1


@pytest.mark.parametrize('bad',['missing','duplicate','frequency','price'])
def test_pair_rejects(bad):
    a,b,d=sample()
    if bad=='missing': b.pop()
    if bad=='duplicate': b.append(b[-1])
    if bad=='frequency': b[0]['frequency']=90
    if bad=='price': b[0]['close']=10.001
    with pytest.raises(ValueError): validate_pair(a,b,d,CODES[0])
