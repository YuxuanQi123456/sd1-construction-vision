"""Coordinator-owned integration evidence over the installed upstream HTTP API."""
import argparse
from decimal import Decimal
import json
import hashlib
from pathlib import Path
import sys
import uuid

from demo_api import DemoAPI, ROOT, utc_now, write_json
from demo_data import MaterialScenario

OUT = ROOT / 'evidence/T04'
CHECKPOINT = ROOT / '.runtime/persistence-checkpoint.json'


def snapshot(api, scenario):
    verified = scenario.verify()
    rows = api.movements(verified['project_id'], verified['item_id'])
    return {'project_id': verified['project_id'], 'item_id': verified['item_id'],
            'locations': verified['locations'], 'balances_t': verified['balances_t'],
            'consumption_cost_cny': verified['consumption_cost_cny'],
            'movement_ids': sorted(row['id'] for row in rows),
            'workspace_id': api.request('GET', '/api/health')['workspace_id']}


def repeat(api):
    rounds = []
    run = uuid.uuid4().hex[:10].upper()
    for number in range(1, 4):
        scenario = MaterialScenario(api, 'ground' if number != 2 else 'underground',
                                    f'SD1-TEST-T02-INTEGRATION-{run}-{number}')
        context = scenario.ready()
        if context['stage'] != 'ready' or api.movements(context['project_id'], context['item_id']):
            raise RuntimeError('Fresh scenario must have zero movements.')
        stages = []
        for key, expected in [('inbound',100),('consume',70),('waste',68),('transfer',68)]:
            scenario.apply_steps({key})
            actual = api.stock(context['project_id'], context['item_id'])
            if Decimal(actual) != Decimal(expected):
                raise RuntimeError(f'{key}: expected {expected}, actual {actual}')
            stages.append({'step':key,'total_t':actual})
        before = snapshot(api, scenario)
        scenario.complete()
        if snapshot(api, scenario) != before:
            raise RuntimeError('Replay changed the business result.')
        rounds.append({'round':number,'stages':stages,'verified':before,
                       'archive':scenario.reset(),'passed':True})
    return {'rounds':rounds,'passed':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['repeat','persistence-before','persistence-after','delivery-check'])
    args=parser.parse_args()
    api=DemoAPI()
    result=None
    exit_code=0
    started=utc_now()
    try:
        api.login()
        if args.phase=='repeat':
            result=repeat(api)
        elif args.phase=='delivery-check':
            expected=json.loads((OUT/'formal-browser/report.json').read_text())['delivered_ready_scenarios']
            verified=[]
            for checkpoint in expected:
                scenario=MaterialScenario(api, checkpoint['scenario'])
                context=scenario.context()
                for field in ('project_id','item_id','locations'):
                    if context[field]!=checkpoint[field]:
                        raise RuntimeError('Delivered object identity changed after final restart.')
                if scenario.validate_movements(context):
                    raise RuntimeError('Delivered scene is not at the empty starting point.')
                if Decimal(api.stock(context['project_id'],context['item_id'])) != 0:
                    raise RuntimeError('Delivered scene stock is not zero.')
                verified.append(context)
            assets=[]
            for name in ('index.html','styles.css','app.js'):
                response=api.client.get('/sd1-demo/'+name)
                response.raise_for_status()
                actual=hashlib.sha256(response.content).hexdigest()
                if actual!=hashlib.sha256((ROOT/'web'/name).read_bytes()).hexdigest():
                    raise RuntimeError('Served static asset differs from integrated source: '+name)
                assets.append({'file':name,'sha256':actual})
            result={'ready_scenarios':verified,'assets':assets,'health':api.request('GET','/api/health'),'passed':True}
        else:
            scenario=MaterialScenario(api, namespace='SD1-TEST-T02-PERSISTENCE')
            if args.phase=='persistence-before':
                scenario.complete()
                result=snapshot(api,scenario)
                write_json(CHECKPOINT,result)
            else:
                expected=json.loads(CHECKPOINT.read_text())
                result=snapshot(api,scenario)
                if result!=expected:
                    raise RuntimeError('Identity, movements or values changed after restart/restore.')
                result={'matched':True,'checkpoint':result}
    except Exception as exc:
        exit_code=1
        result={'error':str(exc)}
    finally:
        report={'phase':args.phase,'started_at':started,'finished_at':utc_now(),
                'exit_code':exit_code,'result':result,'http':api.records}
        write_json(OUT/(args.phase+'.json'),report)
        api.close()
    print(json.dumps({'phase':args.phase,'exit_code':exit_code,'result':result},ensure_ascii=False,indent=2))
    return exit_code


if __name__=='__main__':
    raise SystemExit(main())
