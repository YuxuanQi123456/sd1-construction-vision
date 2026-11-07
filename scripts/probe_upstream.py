"""Readiness and pre-adaptation behavior probe using official HTTP APIs."""
import json
from pathlib import Path
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / 'config/demo.json').read_text())
OUT = ROOT / 'evidence/T01'
OUT.mkdir(parents=True, exist_ok=True)
client = httpx.Client(base_url=CFG['base_url'], trust_env=False, timeout=120)
records = []

def call(method, path, body=None, allowed=(200, 201)):
    res = client.request(method, path, json=body)
    try:
        data = res.json()
    except ValueError:
        data = res.text[:300]
    safe = {k: v for k, v in data.items() if 'token' not in k} if isinstance(data, dict) else data
    records.append({'method': method, 'path': path, 'status': res.status_code, 'response': safe})
    if res.status_code not in allowed:
        (OUT / 'probe-failure.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
        raise RuntimeError(f'{method} {path}: {res.status_code} {safe}')
    return data

call('GET', '/api/health')
call('POST', '/api/v1/users/auth/register/',
     {k: CFG[k] for k in ('email', 'password', 'full_name', 'locale')}, allowed=(200, 201, 400, 409))
token = call('POST', '/api/v1/users/auth/login/',
             {k: CFG[k] for k in ('email', 'password')})['access_token']
client.headers['Authorization'] = 'Bearer ' + token
project = call('POST', '/api/v1/projects/', {
    'name': 'SD1-AUDIT-原版行为核查-' + str(int(time.time())),
    'currency': 'CNY', 'locale': 'zh', 'country_code': 'CN',
    'description': '合成数据；原版接口检查项目，不是正式演示成果',
})
pid = project['id']
prefix = f'/api/v1/site-inventory/projects/{pid}'
loc = call('POST', prefix + '/locations', {'name': '核查A库', 'code': 'A'})
item = call('POST', prefix + '/items', {'name': '合成水泥', 'unit': 't', 'standard_unit_cost': '400', 'currency': 'CNY'})
base = {'item_id': item['id'], 'location_id': loc['id'], 'unit_cost': '400', 'currency': 'CNY'}
call('POST', prefix + '/movements', {**base, 'movement_type': 'INBOUND', 'quantity': '100', 'note': '原版核查入库'})
call('POST', prefix + '/movements', {**base, 'movement_type': 'CONSUMPTION', 'quantity': '101', 'note': '刻意超领：确认原版边界'}, allowed=(201, 409))
call('GET', prefix + '/stock-on-hand')
result = {'scope': '实际官方API；专用合成核查项目', 'project_id': pid,
          'native_ui': f"{CFG['base_url']}/projects/{pid}/site-inventory", 'records': records}
(OUT / 'upstream-probe.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'project_id': pid, 'last_response': records[-1], 'evidence': str(OUT / 'upstream-probe.json')}, ensure_ascii=False))
