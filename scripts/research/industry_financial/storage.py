"""Atomic local units, hashes and cancellation; never writes outside this run."""
from pathlib import Path
from decimal import Decimal
import hashlib
import json
import os
import resource
import time
from .spec import SPEC,TRIAL_SCOPE

ROOT=Path(__file__).resolve().parents[3]
OUTPUT_ROOT=ROOT/'reports/a_share_industry_prosperity_2026q3'

class Cancelled(RuntimeError): pass
class BudgetExceeded(RuntimeError): pass

def encode(value):
    if isinstance(value,Decimal): return str(value)
    raise TypeError(type(value).__name__)

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load(path):
    return json.loads(Path(path).read_text(),parse_float=Decimal)

def atomic_json(path, obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    part=path.with_suffix(path.suffix+'.part')
    with part.open('w') as stream:
        json.dump(obj,stream,ensure_ascii=False,sort_keys=True,indent=2,default=encode)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(part,path)

class RunStore:
    def __init__(self,path,resume=False,scope=TRIAL_SCOPE):
        self.scope=scope
        self.spec_hash=scope.digest()
        self.path=Path(path).resolve()
        if self.path.parent != OUTPUT_ROOT or not self.path.name.startswith(scope.name+'_'):
            raise ValueError('Only a direct study directory matching the explicit execution scope is allowed')
        if self.path.exists() and not (self.path/'run.json').exists() and any(self.path.iterdir()):
            raise ValueError('Nonempty directory without run manifest cannot be adopted')
        self.path.mkdir(exist_ok=True,parents=True)
        self.started=time.monotonic()
        manifest=self.path/'run.json'
        if manifest.exists():
            if not resume: raise ValueError('Existing run requires explicit resume')
            self.state=load(manifest)
            if self.state['spec_hash']!=self.spec_hash:raise ValueError('Spec changed; cannot resume')
        else:
            self.state={'spec_hash':self.spec_hash,'spec':SPEC.manifest(),'status':'CREATED',
                        'db_seconds':0,'elapsed_seconds':0,'completed':0,'total_units':0}
        self.base_elapsed=float(self.state.get('elapsed_seconds',0))
        if scope.name=='formal':
            self.state['execution_scope']=scope.manifest()
            self.state['spec']=dict(SPEC.manifest(),mode='current_company_formal_study',coverage_denominator='current_candidate_industry_known_revenue')
        for name in ('inputs','calculations','evidence','charts'):(self.path/name).mkdir(exist_ok=True)
        self.save()

    def check(self):
        if (self.path/'CANCEL').exists():raise Cancelled('Local cancellation requested')
        if self.base_elapsed+time.monotonic()-self.started>SPEC.total_seconds:raise BudgetExceeded('Study total time budget')
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if os.uname().sysname!='Darwin':rss*=1024
        if rss>SPEC.memory_bytes:raise BudgetExceeded('Study memory budget')
        size=sum(p.stat().st_size for p in (self.path/'inputs').rglob('*') if p.is_file())
        if size>SPEC.disk_bytes:raise BudgetExceeded('Study input disk budget')
        if float(self.state['db_seconds'])>=self.scope.db_seconds:raise BudgetExceeded('Study database budget')

    def save(self,**updates):
        self.state.update(updates)
        self.state['elapsed_seconds']=self.base_elapsed+time.monotonic()-self.started
        atomic_json(self.path/'run.json',self.state)

    def receipt(self,name):return self.path/'evidence'/f'{name}.receipt.json'

    def completed(self,name):
        p=self.receipt(name)
        if not p.exists():return None
        receipt=load(p);artifact=self.path/receipt['artifact']
        if not artifact.exists() or digest(artifact)!=receipt['sha256']:
            raise ValueError('Completed unit hash mismatch: '+name)
        if receipt['spec_hash']!=self.spec_hash:raise ValueError('Unit spec mismatch')
        return receipt

    def seal(self,name,part,rows,fingerprint):
        target=self.path/'inputs'/f'{name}.jsonl'
        os.replace(part,target)
        receipt={'artifact':str(target.relative_to(self.path)),'sha256':digest(target),'rows':rows,
                 'fingerprint':fingerprint,'spec_hash':self.spec_hash}
        atomic_json(self.receipt(name),receipt)
        # The receipt is the completed fact; a state-save failure cannot undo it.
        self.save(completed=len(list((self.path/'evidence').glob('*.receipt.json'))))
        return receipt

    def rows(self,name):
        parts_path=self.path/'evidence/input_parts.json'
        parts=load(parts_path) if parts_path.exists() else {}
        if name in parts:
            for part_name in parts[name]:yield from self.rows(part_name)
            return
        r=self.completed(name)
        if not r:raise ValueError('Missing complete input '+name)
        with (self.path/r['artifact']).open() as stream:
            for line in stream:
                yield json.loads(line,parse_float=Decimal)
