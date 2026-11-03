"""Run the approved financial study in trial or formal scope; source writes are forbidden."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
from .storage import RunStore,Cancelled,atomic_json,load,digest
from .spec import TRIAL_SCOPE,FORMAL_SCOPE
from .extract import extract_trial,audit_exceptions,verify_source
from .analysis import analyze
from .charts import write_preview
from .validation import manual_checks,validate_artifacts,frozen_queries


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--scope',choices=('trial','formal'),default='trial')
    parser.add_argument('--extract-only',action='store_true')
    parser.add_argument('--stop-after',type=int,metavar='completed units')
    parser.add_argument('--offline',action='store_true',help='Only recalculate frozen local inputs; no source verification')
    args=parser.parse_args(argv)
    if args.stop_after is not None and not 1<=args.stop_after<=(151 if args.scope=='formal' else 47):parser.error('stop-after outside execution scope')
    if args.offline and (not args.resume or args.stop_after or args.extract_only):parser.error('offline requires resume and no extraction stop')
    store=RunStore(args.output,args.resume,FORMAL_SCOPE if args.scope=='formal' else TRIAL_SCOPE)
    try:
        if not args.offline:
            if args.scope=='formal':
                from .formal import extract_formal
                extract_formal(store,args.stop_after)
            else:
                extract_trial(store,args.stop_after)
                audit_exceptions(store)
        if args.extract_only:
            print('Frozen inputs saved; no calculation or publication yet.',flush=True);return 0
        # Manual semantic evidence must exist; no CLI flag can manufacture approval.
        quality=load(store.path/'evidence/quality.json')
        if not quality.get('semantic_pass'):raise ValueError('Issuer semantic checks not completed')
        manual_checks(store)
        analyze(store)
        environment=load(store.path/'evidence/render_environment.json')
        if digest(environment['renderer'])!=environment['sha256']:raise ValueError('Installed renderer changed')
        # Rebuild invalidates the previous rendered QA record; preserve the historical receipt.
        qa=store.path/'evidence/browser_qa.json'
        if qa.exists():qa.rename(store.path/'evidence'/('browser_qa_previous_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.json'))
        write_preview(store,environment['renderer'])
        if not args.offline:
            if args.scope=='formal':
                from .formal import saved_queries
                verify_source(store,saved_queries(store))
            else:verify_source(store,frozen_queries(store))
        if args.scope=='formal':
            from .validation import validate_formal,validate_report_snapshot
            result=validate_formal(store)
            from .report import write_snapshot,build_report
            write_snapshot(store)
            build_report(store)
            validate_report_snapshot(store)
        else:result=validate_artifacts(store)
        store.save(status='AWAITING_RENDER_ACCEPTANCE',source_verification='skipped_offline' if args.offline else 'passed',
                   full_market_report_ready=False)
        print(f'{args.scope} calculation artifacts saved. Rendered QA and closeout remain; no source writes or publication.',flush=True)
        return 0
    except Cancelled as exc:
        store.save(status='CANCELLED',reason=str(exc));print(str(exc),flush=True);return 2
    except BaseException as exc:
        store.save(status='FAILED',reason=type(exc).__name__+': '+str(exc));raise

if __name__=='__main__':raise SystemExit(main())
