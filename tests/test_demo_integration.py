"""Verify the actual T02 formal fixtures through T03 UI and back through T02 CLI logic."""
import html
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from demo_api import DemoAPI, utc_now, write_json
from demo_data import MaterialScenario
from playwright.sync_api import sync_playwright, expect

OUT = ROOT / 'evidence/T04/formal-browser'
OUT.mkdir(parents=True, exist_ok=True)
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '/tmp/shuidian-demo-browsers'
api = DemoAPI()
report = {'started_at': utc_now(), 'scope': 'Formal T02 fixtures -> real T03 buttons -> T02 verifier',
          'flows': [], 'external_requests': [], 'page_errors': []}
browser = None
exit_code = 0
try:
    api.login()
    ground = MaterialScenario(api, 'ground')
    underground = MaterialScenario(api, 'underground')
    # Only strictly owned synthetic formal scenarios can be archived/recreated.
    ground.reset()
    underground.reset()
    prepared = ground.prepare()
    empty = underground.ready()
    cfg = OUT / 'fontconfig.xml'
    cfg.write_text('<?xml version="1.0"?><fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include>'
                   '<dir>/mnt/c/Windows/Fonts</dir><cachedir>/tmp/sd1-demo-font-cache</cachedir></fontconfig>')
    with sync_playwright() as playwright:
        env = {**os.environ, 'LD_LIBRARY_PATH': '/tmp/hydro-browser-libs/root/usr/lib/x86_64-linux-gnu',
               'FONTCONFIG_FILE': str(cfg)}
        browser = playwright.chromium.launch(headless=True, args=['--no-proxy-server'], env=env)
        context = browser.new_context(viewport={'width':1920,'height':1080}, locale='zh-CN', reduced_motion='reduce')
        def local_only(route):
            from urllib.parse import urlparse
            if urlparse(route.request.url).hostname not in ('127.0.0.1','localhost','::1'):
                report['external_requests'].append(route.request.url)
                route.abort('blockedbyclient')
            else:
                route.continue_()
        context.route('**/*', local_only)
        page = context.new_page()
        page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
        url = api.config['base_url'] + '/sd1-demo/index.html'
        page.goto(url, wait_until='networkidle')
        expect(page.locator('#project-select option')).to_have_count(2)
        for scenario, state, steps in [(ground, prepared, ['consume','waste','transfer']),
                                       (underground, empty, ['inbound','consume','waste','transfer'])]:
            page.locator('#project-select').select_option(state['project_id'])
            expect(page.locator('#stock-total')).to_have_text('100' if scenario.scenario=='ground' else '0')
            for step in steps:
                expect(page.locator('#step-' + step)).to_be_enabled()
                page.locator('#step-' + step).click()
                expect(page.locator('#step-' + step)).to_be_disabled()
                expect(page.locator('#message')).not_to_contain_text('正在')
            expect(page.locator('#stock-total')).to_have_text('68')
            expect(page.locator('#stock-a')).to_have_text('58')
            expect(page.locator('#stock-b')).to_have_text('10')
            expect(page.locator('#consume-cost')).to_have_text('12,000')
            verified = scenario.verify()
            report['flows'].append({'scenario':scenario.scenario, 'verified':verified, 'browser_steps':steps})
            page.screenshot(path=str(OUT / (scenario.scenario + '-complete.png')), full_page=True, animations='disabled')
        if report['external_requests'] or report['page_errors']:
            raise RuntimeError('Unexpected external requests or page errors')
        # Deliver a clean, usable starting state for the user, preserving old records via archive.
        ready = []
        for scenario in (ground,underground):
            scenario.reset()
            ready.append(scenario.ready())
        report['delivered_ready_scenarios'] = ready
        page.goto(url, wait_until='networkidle')
        expect(page.locator('#project-select option')).to_have_count(2)
        expect(page.locator('#stock-total')).to_have_text('0')
        expect(page.locator('#step-inbound')).to_be_enabled()
        page.screenshot(path=str(OUT / 'ready-for-user.png'), full_page=True, animations='disabled')
        browser.close()
except Exception as exc:
    exit_code = 1
    report['error'] = str(exc)
finally:
    report.update(exit_code=exit_code, finished_at=utc_now(), http=api.records)
    write_json(OUT / 'report.json', report)
    api.close()
print(json.dumps({'exit_code':exit_code,'flows':len(report['flows']),'error':report.get('error'),
                  'ready':report.get('delivered_ready_scenarios')},ensure_ascii=False,indent=2))
raise SystemExit(exit_code)
