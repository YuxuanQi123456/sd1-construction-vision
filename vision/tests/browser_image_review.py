"""Upload one real video frame as an image and capture an actual UI response."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]

async def run(args, record):
    from playwright.async_api import async_playwright, expect
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp('http://127.0.0.1:9226')
        context = await browser.new_context(viewport={'width':1440,'height':1080},locale='zh-CN')
        page = await context.new_page()
        async def local_only(route):
            if urlparse(route.request.url).hostname in ('127.0.0.1','localhost','::1'):
                await route.continue_()
            else:
                record['blocked_external'].append(route.request.url)
                await route.abort()
        await context.route('**/*',local_only)
        try:
            await page.goto('http://127.0.0.1:8766',wait_until='domcontentloaded')
            await expect(page.get_by_role('heading',name='施工视频 AI 隐患审查')).to_be_visible()
            await page.locator('input[type=file]').first.set_input_files(
                {'name':args.image.name,'mimeType':'image/jpeg' if args.image.suffix.lower() in ('.jpg','.jpeg') else 'image/png','buffer':args.image.read_bytes()})
            uploaded=page.locator('[role="log"] img').first
            await expect(uploaded).to_be_visible(timeout=60000)
            question=args.question
            await page.locator('textarea').first.fill(question)
            start=time.monotonic()
            await page.get_by_role('button',name=re.compile('Submit')).click()
            answer=page.locator('[data-testid="bot"]').last
            await expect(answer).to_contain_text('本次为图片',timeout=180000)
            record.update(question=question,answer=await answer.inner_text(),
                          elapsed_seconds=round(time.monotonic()-start,3),
                          rendered_image=await uploaded.evaluate('(i)=>({width:i.naturalWidth,height:i.naturalHeight,src:i.currentSrc})'),
                          video_elements=await page.locator('[role="log"] video').count())
            assert record['video_elements']==0 and record['rendered_image']['width']>0
            await page.screenshot(path=str(args.output/'image-answer.png'),full_page=True)
            if args.follow_up:
                await page.locator('textarea').first.fill(args.follow_up)
                started=time.monotonic()
                await page.get_by_role('button',name=re.compile('Submit')).click()
                await expect(page.locator('[data-testid="bot"]')).to_have_count(2,timeout=180000)
                last=page.locator('[data-testid="bot"]').last
                await expect(last).to_contain_text('本次为图片',timeout=180000)
                record['follow_up']={'question':args.follow_up,'answer':await last.inner_text(),
                                     'elapsed_seconds':round(time.monotonic()-started,3)}
                await page.screenshot(path=str(args.output/'image-follow-up.png'),full_page=True)
            if args.check_photo_presets:
                record['photo_presets']=[]
                for sample in json.loads((ROOT/'vision/config/samples.json').read_text()):
                    if sample.get('media_type')!='image': continue
                    await page.get_by_role('listbox').first.click()
                    await page.get_by_role('option',name=sample['title'],exact=True).click()
                    await page.get_by_role('button',name='载入样例（开启新会话）',exact=True).click()
                    await page.wait_for_function('''name => [...document.querySelectorAll('[role="log"] img')].some(i => i.currentSrc.includes(name) && i.complete && i.naturalWidth>0)''',arg=sample['file'],timeout=60000)
                    await expect(page.locator('[data-testid="bot"]')).to_have_count(0)
                    bounds=await uploaded.bounding_box()
                    area=await page.locator('[role="log"]').bounding_box()
                    assert bounds and area and 0<bounds['height']<=401
                    assert bounds['y']>=area['y']-2 and bounds['y']+bounds['height']<=area['y']+area['height']+2
                    record['photo_presets'].append({'sample':sample['id'],'bounds':bounds,'chat_bounds':area,'decoded':True})
                    await page.screenshot(path=str(args.output/('preset-'+sample['id']+'.png')),full_page=True)
            record['technical_passed']=True
            record['business_accuracy']='Requires comparison with source image; not inferred from generation success.'
        except Exception as error:
            record['failure']=f'{type(error).__name__}: {error}'
            await page.screenshot(path=str(args.output/'failure.png'),full_page=True)
            raise
        finally:
            await context.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,default=ROOT/'evidence/V02/run-08-final/frames/excavator-loading-06-15.10s.png')
    parser.add_argument('--output',type=Path,default=ROOT/'evidence/V03/image')
    parser.add_argument('--source',default='Frame from excavator-loading.webm; KEmel49 / Wikimedia Commons, CC BY-SA 4.0; see vision/config/samples.json')
    parser.add_argument('--question',default='请描述人员、工具或机械、正在处理的物体及可见防护用品。哪些可见现象值得现场复核？看不清的细节请明确说明。')
    parser.add_argument('--check-photo-presets',action='store_true')
    parser.add_argument('--follow-up')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    record={'at':datetime.now(timezone.utc).isoformat(),'image':str(args.image),
            'image_sha256':hashlib.sha256(args.image.read_bytes()).hexdigest(),
            'source':args.source,
            'blocked_external':[],'technical_passed':False}
    try: asyncio.run(run(args,record))
    finally:
        (args.output/'report.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(record,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
