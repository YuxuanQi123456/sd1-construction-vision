"""Real browser layout/upload smoke only; never click inference or start Qwen."""
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect

os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.environ.get('BRAND_LAYOUT_OUTPUT', ROOT/'evidence/V11/brand-layout'))
OUTPUT.mkdir(parents=True, exist_ok=True)
REPORT = {'at': datetime.now(timezone.utc).isoformat(), 'scope': 'Brand layout, Chinese controls and upload preview. No inference or Qwen calls.',
          'passed': False, 'page_errors': [], 'external_requests': [], 'layouts': []}


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp('http://127.0.0.1:9226')
        context = await browser.new_context(viewport={'width': 1440, 'height': 1100}, locale='zh-CN')
        async def local_only(route):
            if urlparse(route.request.url).hostname in {'127.0.0.1', 'localhost', '::1'}:
                await route.continue_()
            else:
                REPORT['external_requests'].append(route.request.url)
                await route.abort()
        await context.route('**/*', local_only)
        page = await context.new_page()
        page.on('pageerror', lambda error: REPORT['page_errors'].append(str(error)))
        try:
            await page.goto('http://127.0.0.1:8767', wait_until='domcontentloaded')
            await expect(page.get_by_role('heading', name='影像识别与复核', exact=True)).to_be_visible(timeout=30000)
            await expect(page.locator('[data-testid="stApp"]')).to_have_attribute('data-test-script-state', 'notRunning')
            await expect(page).to_have_title('水电一局 · 施工视觉AI')
            logo = page.locator('.sd1-logo')
            await expect(logo).to_be_visible()
            assert await logo.evaluate('(img) => img.complete && img.naturalWidth === 344 && img.naturalHeight === 63')
            data = base64.b64decode((await logo.get_attribute('src')).split(',', 1)[1])
            assert data == (ROOT/'sitewatch/branding/logo.png').read_bytes()
            REPORT['logo_sha256'] = hashlib.sha256(data).hexdigest()
            await expect(page.locator('.sd1-step')).to_have_count(3)
            await expect(page.get_by_role('radio', name='清晰演示素材', exact=True)).to_be_checked()
            await expect(page.get_by_role('button', name='开始识别与复核', exact=True)).to_be_enabled()
            REPORT['primary_color'] = await page.get_by_role('button', name='开始识别与复核', exact=True).evaluate('(n) => getComputedStyle(n).backgroundColor')
            assert REPORT['primary_color'] == 'rgb(1, 83, 159)'
            await page.locator('.sd1-masthead').scroll_into_view_if_needed()
            await page.screenshot(path=str(OUTPUT/'01-desktop.png'))
            await page.get_by_text('自己上传', exact=True).click()
            await expect(page.get_by_text('从一张现场照片开始', exact=True)).to_be_visible()
            source = ROOT/'downloads/vision-samples/niosh-runway-worker.jpg'
            await page.locator('input[type=file]').set_input_files({'name': source.name, 'mimeType': 'image/jpeg', 'buffer': source.read_bytes()})
            await expect(page.get_by_text('当前影像：'+source.name, exact=True)).to_be_visible()
            await expect(page.get_by_role('button', name='开始识别与复核', exact=True)).to_be_enabled()
            await expect(page.get_by_role('checkbox', name='保留原片画质（较慢）', exact=True)).to_be_checked()
            await expect(page.get_by_role('button', name='下载原始检测 JSON', exact=True)).to_have_count(0)
            REPORT['upload_preview_without_inference'] = True
            await page.get_by_text('清晰演示素材', exact=True).click()
            for width, height in [(1440,1100), (1024,900), (390,844)]:
                await page.set_viewport_size({'width':width,'height':height})
                collapse = page.locator('[data-testid="stSidebarCollapseButton"] button')
                if width == 390:
                    await page.wait_for_timeout(350)  # Streamlit's responsive sidebar transition.
                    box = await collapse.bounding_box()
                    if box and 0 <= box['x'] + box['width']/2 <= width:
                        await collapse.click()
                await page.locator('.sd1-masthead').scroll_into_view_if_needed()
                await expect(logo).to_be_visible()
                layout = await page.locator('.sd1-masthead').evaluate('''(n) => {const r=n.getBoundingClientRect();
                    return {left:r.left,right:r.right,viewport:innerWidth,pageWidth:document.documentElement.scrollWidth};}''')
                assert layout['left'] >= 0 and layout['right'] <= width + 1, layout
                assert layout['pageWidth'] <= width + 1, layout
                REPORT['layouts'].append(layout)
                await page.screenshot(path=str(OUTPUT/f'layout-{width}.png'))
            await expect(page.locator('[data-testid="stException"]')).to_have_count(0)
            assert REPORT['page_errors'] == []
            assert REPORT['external_requests'] == []
            REPORT['passed'] = True
        except Exception as error:
            REPORT['error'] = f'{type(error).__name__}: {error}'
            await page.screenshot(path=str(OUTPUT/'failure.png'))
            raise
        finally:
            await context.close()
            await browser.close()


try:
    asyncio.run(run())
except Exception as error:
    REPORT['error'] = f'{type(error).__name__}: {error}'
    raise
finally:
    (OUTPUT/'report.json').write_text(json.dumps(REPORT,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(REPORT,ensure_ascii=False,indent=2))
