"""Frozen, bounded trial specification; methodology v1 sections 1-10.5."""
from dataclasses import asdict, dataclass
from decimal import Decimal, getcontext
from hashlib import sha256
import json

getcontext().prec = 28

@dataclass(frozen=True)
class StudySpec:
    dates: tuple = tuple(f'{y}-{m}-{d}' for y in (2024, 2025, 2026) for m, d in (('03','31'),('06','30'),('09','30'),('12','31')) if (y,m) != (2026,'12'))
    snapshot: str = '2026-10-30'
    baseline: str = 'eastmoney_dc_industry_hierarchy.cn_a.v1'
    roots: tuple = ('BK0438.DC','BK1201.DC','BK1206.DC','BK1209.DC','BK1216.DC')
    excluded: tuple = ('002717.SZ','002827.SZ','601326.SH','605258.SH','688121.SH','688496.SH')
    per_root: int = 20
    max_codes: int = 100
    max_rows: int = 4400
    max_exception_rows: int = 260
    max_member_rows: int = 300
    max_tree_rows: int = 305
    db_seconds: int = 180
    total_seconds: int = 1800
    memory_bytes: int = 512*1024*1024
    disk_bytes: int = 150*1024*1024
    unit_seconds: int = 30
    batch_rows: int = 2000
    min_companies: int = 5
    min_peers: int = 5
    min_coverage: str = '0.90'
    near_zero_profit: str = '0.001'
    amount_tolerance: str = '1'
    day_year: int = 360
    revenue_season_weight: str = '0.5'
    dimension_weights: tuple = ('0.25','0.25','0.25','0.25')
    sensitivity_weights: tuple = ('0.15','0.20','0.25','0.30','0.35')
    model_weights: tuple = ('0.25','0.5','0.75')

    def __post_init__(self):
        if len(self.dates)!=11 or min(self.dates)!='2024-03-31' or max(self.dates)!='2026-09-30':
            raise ValueError('Report date range cannot change')
        if any(getattr(self,k)!=type(self).__dataclass_fields__[k].default for k in ('dates','roots','excluded')):
            raise ValueError('Approved dates, roots and exclusions cannot change')
        if self.per_root != 20 or self.max_codes != 100 or len(self.roots)!=5:
            raise ValueError('Trial sample cannot change')
        if self.revenue_season_weight != '0.5' or self.dimension_weights != ('0.25',)*4:
            raise ValueError('Approved main weights cannot change')

    def manifest(self):
        return {'values':asdict(self),'mode':'bounded_engineering_trial',
                'confirmed':['scope','revenue_50_50','margin_seasonal_formula','seven_metric_weights','nine_quadrants'],
                'provisional':['coverage_and_company_gates','trend_tags','cashflow_and_scenario','percentile_and_sensitivity','financial_comparison'],
                'coverage_denominator':'selected_trial_codes_only','formal_investment_ranking':False}

    def digest(self):
        return sha256(json.dumps(self.manifest(),sort_keys=True,ensure_ascii=False).encode()).hexdigest()

SPEC=StudySpec()
IDENTITY=('ts_code','end_date','ann_date','f_ann_date','report_type','comp_type','end_type','update_flag','fetched_at','source_content_hash')
FIELDS={
 'income':('revenue','total_revenue','oper_cost','operate_profit','n_income','n_income_attr_p'),
 'balancesheet':('accounts_receiv','inventories','accounts_pay','total_assets','total_liab','total_hldr_eqy_exc_min_int','total_hldr_eqy_inc_min_int','fix_assets_total','contract_assets','contract_liab'),
 'cashflow':('n_cashflow_act','c_fr_sale_sg','c_pay_acq_const_fiolta'),
 'fina_indicator':('profit_dedt','q_dtprofit'),
 'valuation':('close','total_mv','total_share','pe_ttm','pb','ps_ttm','dv_ttm'),
}
TABLES={k:'core_serving.equity_'+k for k in ('income','balancesheet','cashflow')}
TABLES.update(fina_indicator='raw_tushare.fina_indicator',valuation='core_serving.equity_daily_basic')


@dataclass(frozen=True)
class ExecutionScope:
    """Execution limits only; the reviewed financial method remains SPEC."""
    name: str = 'trial'

    def __post_init__(self):
        if self.name not in ('trial','formal'):raise ValueError('Unknown execution scope')

    @property
    def max_codes(self):return 5571 if self.name=='formal' else SPEC.max_codes
    @property
    def batch_rows(self):return 2000 if self.name=='formal' else SPEC.max_codes
    @property
    def member_batch_codes(self):return 500 if self.name=='formal' else SPEC.max_codes
    @property
    def max_member_rows(self):return 25000 if self.name=='formal' else SPEC.max_member_rows
    @property
    def max_tree_rows(self):return 496 if self.name=='formal' else SPEC.max_tree_rows
    @property
    def max_rows(self):return 245124 if self.name=='formal' else SPEC.max_rows
    @property
    def db_seconds(self):return 900 if self.name=='formal' else SPEC.db_seconds

    def manifest(self):
        return {k:getattr(self,k) for k in ('name','max_codes','batch_rows','member_batch_codes','max_member_rows','max_tree_rows','max_rows','db_seconds')}

    def digest(self):
        if self.name=='trial':return SPEC.digest()
        return sha256(json.dumps({'research':SPEC.manifest(),'execution':self.manifest()},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

TRIAL_SCOPE=ExecutionScope()
FORMAL_SCOPE=ExecutionScope('formal')
