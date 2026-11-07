"""Exercise the installed static guide against real upstream HTTP APIs and Chromium.

Only creates SD1-TEST-T03-* projects. It does not alter formal or T02 projects.
Public-network requests are blocked; evidence omits all authentication headers/tokens.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import html
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / 'config/demo.json').read_text())
MARKER = '水电一局演示｜自制合成数据'
STEPS = ['inbound', 'consume', 'waste', 'transfer']


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-path', default='/tmp/shuidian-demo-browsers')
    parser.add_argument('--library-path', help='Optional explicit directory for Chromium shared libraries')
    parser.add_argument('--font-dir', type=Path, help='Optional local system font directory for this browser run; no fonts are copied or shipped')
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence/T03/browser')
    args = parser.parse_args()
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = args.browser_path
    args.output.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    report = {'started_at': started, 'command': sys.argv, 'base_url': CFG['base_url'],
              'versions': {'python': sys.version.split()[0], 'playwright': importlib.metadata.version('playwright')},
              'network_policy': 'httpx trust_env=False; Chromium --no-proxy-server; block non-local browser requests',
              'scope': 'Real APIs and browser button writes in new SD1-TEST-T03 projects only',
              'checks': [], 'api': [], 'requests': [], 'responses_failed': [], 'console_errors': [],
              'page_errors': [], 'request_errors': [], 'external_requests': []}
    client = httpx.Client(base_url=CFG['base_url'], trust_env=False, timeout=60)

    def call(method, path, body=None):
        response = client.request(method, path, json=body)
        report['api'].append({'method': method, 'path': path, 'status': response.status_code})
        response.raise_for_status()
        return response.json()

    def check(name, details):
        report['checks'].append({'name': name, 'passed': True, 'details': details})

    browser = None
    try:
        call('GET', '/api/health')
        auth = call('POST', '/api/v1/users/auth/login/', {k: CFG[k] for k in ('email', 'password')})
        client.headers['Authorization'] = 'Bearer ' + auth['access_token']
        suffix = str(time.time_ns())
        ns = 'SD1-TEST-T03-GROUND-' + suffix
        project = call('POST', '/api/v1/projects/', {'name': ns + '｜地上厂区基础材料演示', 'description': MARKER + '｜T03独立浏览器验收',
                       'currency': 'CNY', 'locale': 'zh', 'country_code': 'CN'})
        # v19 accepts metadata on ProjectUpdate, but silently ignores it on ProjectCreate.
        project = call('PATCH', '/api/v1/projects/' + project['id'],
                       {'metadata': {'sd1_namespace': ns, 'sd1_scenario': 'ground', 'sd1_synthetic': True,
                                     'sd1_managed_by': 'tests/browser_demo.py', 'sd1_fixture_version': 1}})
        pid = project['id']
        prefix = f'/api/v1/site-inventory/projects/{pid}'
        locations = {code: call('POST', prefix + '/locations', {'name': name, 'code': code})
                     for code, name in [('A', 'A 库 · 厂区主库（合成）'), ('B', 'B 库 · 施工接收库（合成）')]}
        item = call('POST', prefix + '/items', {'name': '示例水泥（合成）', 'sku': 'SD1-CEMENT',
                    'unit': 't', 'standard_unit_cost': '400', 'currency': 'CNY'})
        report['fixture'] = {'project_id': pid, 'namespace': ns, 'item_id': item['id'],
                             'locations': {k: v['id'] for k, v in locations.items()}}
        url = CFG['base_url'] + '/sd1-demo/index.html?project_id=' + pid

        with sync_playwright() as playwright:
            browser_env = os.environ.copy()
            if args.library_path:
                browser_env['LD_LIBRARY_PATH'] = args.library_path
                report['browser_library_path'] = args.library_path
            if args.font_dir:
                if not args.font_dir.is_dir():
                    raise ValueError('The explicit font directory does not exist')
                fontconfig = args.output / 'fontconfig.xml'
                fontconfig.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig>'
                                      '<include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
                                      '<dir>' + html.escape(str(args.font_dir.resolve())) + '</dir>'
                                      '<cachedir>/tmp/sd1-demo-font-cache</cachedir></fontconfig>')
                browser_env['FONTCONFIG_FILE'] = str(fontconfig.resolve())
                report['browser_font_dir'] = str(args.font_dir.resolve())
            browser = playwright.chromium.launch(headless=True, args=['--no-proxy-server'], env=browser_env)
            context = browser.new_context(viewport={'width': 1920, 'height': 1080}, locale='zh-CN', reduced_motion='reduce')
            stage = {'name': 'real_flow'}

            def guard(route):
                host = urlparse(route.request.url).hostname
                if host not in ('127.0.0.1', 'localhost', '::1'):
                    report['external_requests'].append({'url': route.request.url, 'stage': stage['name']})
                    route.abort('blockedbyclient')
                else:
                    route.continue_()

            context.route('**/*', guard)
            page = context.new_page()
            page.on('request', lambda req: report['requests'].append({'method': req.method, 'url': req.url, 'resource_type': req.resource_type, 'stage': stage['name']}))
            page.on('response', lambda res: report['responses_failed'].append({'url': res.url, 'status': res.status, 'stage': stage['name']}) if res.status >= 400 else None)
            page.on('console', lambda msg: report['console_errors'].append({'text': msg.text, 'stage': stage['name']}) if msg.type == 'error' else None)
            page.on('pageerror', lambda error: report['page_errors'].append({'text': str(error), 'stage': stage['name']}))
            page.on('requestfailed', lambda req: report['request_errors'].append({'url': req.url, 'failure': req.failure, 'stage': stage['name']}))
            page.goto(url, wait_until='networkidle')
            report['initial_message'] = page.locator('#message').inner_text()
            expect(page.locator('#step-inbound')).to_be_enabled(timeout=30000)
            expect(page.locator('#stock-total')).to_have_text('0')
            assert page.locator('#project-select option').count() == 1
            page.screenshot(path=str(args.output / '01-start-1920.png'), full_page=True, animations='disabled')

            page.locator('#step-inbound').click()
            expect(page.locator('#stock-total')).to_have_text('100', timeout=30000)
            expect(page.locator('#step-consume')).to_be_enabled()
            expect(page.locator('#step-inbound')).to_be_disabled()
            page.screenshot(path=str(args.output / '02-inbound-1920.png'), full_page=True, animations='disabled')
            page.locator('#step-consume').dblclick()
            expect(page.locator('#consume-cost')).to_have_text('12,000', timeout=30000)
            expect(page.locator('#step-waste')).to_be_enabled()
            rows = call('GET', prefix + '/movements?limit=201')
            assert len(rows) == 2
            check('real_button_click_and_double_click', 'Inbound click and consume double-click created exactly two original upstream movements.')

            # An explicit injected HTTP failure demonstrates the UI path; no server write occurs.
            stage['name'] = 'injected_503_failure'
            def fail_write(route):
                if route.request.method == 'POST':
                    route.fulfill(status=503, content_type='application/json', body=json.dumps({'detail': '浏览器验收注入：暂时不可用'}, ensure_ascii=False))
                else:
                    route.continue_()
            page.route('**/movements', fail_write)
            page.locator('#step-waste').click()
            expect(page.locator('#message')).to_contain_text('应用返回 503', timeout=30000)
            expect(page.locator('#step-waste')).to_be_disabled()
            assert len(call('GET', prefix + '/movements?limit=201')) == 2
            page.screenshot(path=str(args.output / '03-visible-failure.png'), full_page=True, animations='disabled')
            page.unroute('**/movements', fail_write)
            stage['name'] = 'real_flow'
            page.locator('#refresh').click()
            expect(page.locator('#step-waste')).to_be_enabled(timeout=30000)
            page.locator('#step-waste').click()
            expect(page.locator('#stock-total')).to_have_text('68', timeout=30000)
            expect(page.locator('#step-transfer')).to_be_enabled()
            page.locator('#step-transfer').click()
            expect(page.locator('#stock-a')).to_have_text('58', timeout=30000)
            expect(page.locator('#stock-b')).to_have_text('10')
            expect(page.locator('#completeness')).to_contain_text('已取到完整四笔流水')
            check('visible_failure_and_recovery', 'Injected POST 503 visibly blocked actions, left two movements; real retry after refresh completed remaining steps.')
            page.screenshot(path=str(args.output / '04-complete-1920.png'), full_page=True, animations='disabled')
            assert page.locator('#native-link').get_attribute('href') == f'/projects/{pid}/site-inventory'

            rows = call('GET', prefix + '/movements?limit=201')
            assert len(rows) == 4
            ids_before = sorted(row['id'] for row in rows)
            for step in STEPS:
                assert sum(f'[sd1_step={step}]' in (row['note'] or '') for row in rows) == 1
            for code, expected in [('A', '58'), ('B', '10')]:
                stock = call('GET', prefix + '/stock-on-hand?location_id=' + locations[code]['id'])
                assert Decimal(next(r['on_hand'] for r in stock['rows'] if r['item_id'] == item['id'])) == Decimal(expected)
            total = call('GET', prefix + '/stock-on-hand')
            assert Decimal(next(r['on_hand'] for r in total['rows'] if r['item_id'] == item['id'])) == Decimal('68')
            consume = next(row for row in rows if row['movement_type'] == 'CONSUMPTION')
            assert Decimal(consume['quantity']) * Decimal(consume['unit_cost']) == Decimal('12000')
            report['final_movements'] = rows
            report['final_stock'] = total
            check('upstream_balances_and_amount', {'total_t': 68, 'A_t': 58, 'B_t': 10, 'consumption_CNY': 12000, 'movements': 4})

            page.reload(wait_until='networkidle')
            expect(page.locator('#completeness')).to_contain_text('已取到完整四笔流水', timeout=30000)
            for step in STEPS:
                expect(page.locator('#step-' + step)).to_be_disabled()
            page.locator('#refresh').click()
            expect(page.locator('#message')).to_contain_text('本次读取没有新增流水', timeout=30000)
            ids_after = sorted(row['id'] for row in call('GET', prefix + '/movements?limit=201'))
            assert ids_before == ids_after
            check('reload_and_refresh_idempotence', {'movement_ids_before': ids_before, 'movement_ids_after': ids_after})
            page.set_viewport_size({'width': 1366, 'height': 768})
            page.screenshot(path=str(args.output / '05-complete-1366.png'), full_page=True, animations='disabled')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            check('laptop_layout', '1366×768: no horizontal page overflow; full-page screenshot retained.')

            # Simulated boundary responses test front-end guard logic; they are not claimed as real ledger content.
            stage['name'] = 'simulated_truncation_guard'
            def capped_ledger(route):
                route.fulfill(status=200, content_type='application/json', body=json.dumps([rows[0]] * 201))
            page.route('**/movements?limit=201', capped_ledger)
            page.locator('#refresh').click()
            expect(page.locator('#message')).to_contain_text('流水达到本次读取上限', timeout=30000)
            expect(page.locator('#consume-cost')).to_have_text('—')
            for step in STEPS:
                expect(page.locator('#step-' + step)).to_be_disabled()
            check('simulated_truncation_guard', '201-row intercepted response blocks writes and clears cost; UI does not claim complete four movements.')
            page.unroute('**/movements?limit=201', capped_ledger)
            stage['name'] = 'simulated_permission_guard'
            me = call('GET', '/api/v1/users/me/')
            me['permissions'] = ['site_inventory.read']
            def readonly_user(route):
                route.fulfill(status=200, content_type='application/json', body=json.dumps(me))
            page.route('**/users/me/', readonly_user)
            page.locator('#refresh').click()
            expect(page.locator('#message')).to_contain_text('没有原生材料台账写入权限', timeout=30000)
            for step in STEPS:
                expect(page.locator('#step-' + step)).to_be_disabled()
            check('simulated_permission_guard', 'Intercepted read-only permissions disable all write controls; no POST is emitted.')
            page.unroute('**/users/me/', readonly_user)

            stage['name'] = 'simulated_owner_guard'
            foreign_project = {**project, 'owner_id': '11111111-1111-4111-8111-111111111111'}
            def foreign_owner(route):
                route.fulfill(status=200, content_type='application/json', body=json.dumps(foreign_project))
            page.route('**/api/v1/projects/' + pid, foreign_owner)
            page.locator('#refresh').click()
            expect(page.locator('#message')).to_contain_text('不是该合成项目的所有者', timeout=30000)
            for step in STEPS:
                expect(page.locator('#step-' + step)).to_be_disabled()
            check('simulated_owner_guard', 'Matching metadata with another owner is rejected even for a global administrator; no POST emitted.')
            page.unroute('**/api/v1/projects/' + pid, foreign_owner)

            stage['name'] = 'real_scope_guard'
            unmarked = call('POST', '/api/v1/projects/', {'name': 'SD1-TEST-T03-GROUND-unmarked-' + suffix,
                            'description': 'T03负例：无正式合成标识，仅验收拒绝访问', 'currency': 'CNY', 'locale': 'zh', 'country_code': 'CN'})
            page.goto(CFG['base_url'] + '/sd1-demo/index.html?project_id=' + unmarked['id'], wait_until='networkidle')
            expect(page.locator('#message')).to_contain_text('不属于已标识', timeout=30000)
            for step in STEPS:
                expect(page.locator('#step-' + step)).to_be_disabled()
            assert call('GET', f"/api/v1/site-inventory/projects/{unmarked['id']}/movements?limit=201") == []
            check('unmarked_project_rejected', {'project_id': unmarked['id'], 'movements': 0})
            stage['name'] = 'default_discovery'
            page.goto(CFG['base_url'] + '/sd1-demo/index.html', wait_until='networkidle')
            expect(page.locator('#message')).not_to_contain_text('正在连接本机演示账户', timeout=30000)
            option_ids = page.locator('#project-select option').evaluate_all('(options) => options.map(o => o.value)')
            assert pid not in option_ids and unmarked['id'] not in option_ids
            check('default_project_scope', 'Default discovery excludes all SD1-TEST-T03 projects; no test data selected implicitly.')

            assert not report['external_requests'], report['external_requests']
            assert not report['page_errors'], report['page_errors']
            assert not report['request_errors'], report['request_errors']
            unexpected_http = [r for r in report['responses_failed'] if r['stage'] != 'injected_503_failure']
            unexpected_console = [r for r in report['console_errors'] if r['stage'] != 'injected_503_failure']
            assert not unexpected_http, unexpected_http
            assert not unexpected_console, unexpected_console
            check('no_public_resources_or_unexpected_browser_errors', {
                'external_requests': 0, 'page_errors': 0, 'request_errors': 0,
                'expected_injected_http_errors': len(report['responses_failed']),
                'expected_injected_console_errors': len(report['console_errors']),
                'local_requests_observed': len(report['requests'])})

            # Use the upstream's real login form and its own session. Never manufacture browser auth storage.
            stage['name'] = 'native_upstream_ui'
            native = context.new_page()
            native.set_viewport_size({'width': 1920, 'height': 1080})
            report['native_errors'] = []
            native.on('console', lambda msg: report['native_errors'].append({'kind': 'console', 'text': msg.text}) if msg.type == 'error' else None)
            native.on('pageerror', lambda error: report['native_errors'].append({'kind': 'pageerror', 'text': str(error)}))
            native.on('request', lambda req: report['requests'].append({'method': req.method, 'url': req.url, 'resource_type': req.resource_type, 'stage': stage['name']}))
            native.on('requestfailed', lambda req: report['native_errors'].append({'kind': 'requestfailed', 'url': req.url, 'failure': req.failure}))
            native.on('response', lambda res: report['native_errors'].append({'kind': 'http', 'url': res.url, 'status': res.status}) if res.status >= 400 else None)
            native.goto(CFG['base_url'] + '/login', wait_until='networkidle')
            native.locator('input[type=email]').fill(CFG['email'])
            native.locator('input[type=password]').fill(CFG['password'])
            with native.expect_response(lambda response: '/users/auth/login' in response.url and response.request.method == 'POST') as login_response:
                native.locator('button[type=submit]').click()
            assert login_response.value.status == 200
            expect(native.locator('input[type=password]')).not_to_be_visible(timeout=30000)
            native.wait_for_load_state('networkidle')
            native.goto(CFG['base_url'] + f'/projects/{pid}/site-inventory', wait_until='networkidle')
            later = native.get_by_role('button', name='稍后', exact=True)
            if later.count() and later.is_visible():
                later.click()
            collapse = native.get_by_role('button', name='收起分析', exact=True)
            if collapse.count() and collapse.is_visible():
                collapse.click()
            (args.output / 'native-initial-text.txt').write_text('\n'.join(line.rstrip() for line in native.locator('body').inner_text().splitlines()) + '\n')
            expect(native.get_by_text('示例水泥（合成）', exact=True).first).to_be_visible(timeout=30000)
            stock_row = native.locator('tr').filter(has_text='示例水泥（合成）').first
            expect(stock_row).to_contain_text('68')
            (args.output / 'native-stock-text.txt').write_text('\n'.join(line.rstrip() for line in native.locator('body').inner_text().splitlines()) + '\n')
            native.screenshot(path=str(args.output / '06-native-stock-1920.png'), full_page=True, animations='disabled')
            native.get_by_text('出入库记录', exact=True).click()
            for step in STEPS:
                expect(native.get_by_text(re.compile(re.escape(f'[sd1_step={step}]')))).to_be_visible(timeout=30000)
            (args.output / 'native-movements-text.txt').write_text('\n'.join(line.rstrip() for line in native.locator('body').inner_text().splitlines()) + '\n')
            native.screenshot(path=str(args.output / '07-native-ledger-1920.png'), full_page=True, animations='disabled')
            check('native_login_stock_and_four_movements', {'project_id': pid, 'login_status': 200, 'stock_t': 68,
                  'step_notes_visible': STEPS, 'native_url': native.url, 'auth': 'Actual upstream login form and normal session; no manual auth storage'})
            assert not [e for e in report['native_errors'] if e['kind'] != 'requestfailed' or e.get('failure') != 'net::ERR_ABORTED'], report['native_errors']
            assert not report['external_requests'], report['external_requests']
            native.goto(url, wait_until='networkidle')
            expect(native.locator('#completeness')).to_contain_text('已取到完整四笔流水', timeout=30000)
            check('return_to_guide_after_native_session', 'Native login and application visit did not prevent reopening the static guide in the same browser context.')
            browser.close()
            browser = None
        report['exit_code'] = 0
    except Exception as exc:
        report['exit_code'] = 1
        report['failure'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        client.close()
    print(json.dumps({'passed': len(report['checks']), 'project_id': report['fixture']['project_id'], 'report': str(args.output / 'report.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
