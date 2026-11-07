"""Verify local HD assets, lossless downloads, large view, and retained uploads."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
from urllib.parse import urlparse

import cv2
import numpy as np

from browser_verify import wait_script_idle


def digest(data):
    return hashlib.sha256(data).hexdigest()


def png_dimensions(data):
    assert data.startswith(b'\x89PNG\r\n\x1a\n'), 'Preserved frame must be PNG'
    return list(struct.unpack('>II', data[16:24]))


def native_first_frame(path, project_root):
    # Compare against the exact decoder used by inference. The Playwright
    # environment has OpenCV 5, whose video color conversion differs from 4.12.
    code = '''import cv2, hashlib, json, sys
from pathlib import Path
path = Path(sys.argv[1])
if path.suffix.lower() in {'.jpg', '.jpeg', '.png'}:
    frame = cv2.imread(str(path))
else:
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        assert ok, 'Cannot independently decode source frame'
    finally:
        capture.release()
assert frame is not None
print(json.dumps({'sha256': hashlib.sha256(frame.tobytes()).hexdigest(),
                  'dimensions': [frame.shape[1], frame.shape[0]],
                  'opencv': cv2.__version__}))
'''
    python = project_root/'.runtime/sitewatch-env/bin/python'
    return json.loads(subprocess.check_output([str(python), '-c', code, str(path)], text=True))


def saved_review(project_root, result):
    reviews = project_root / '.runtime/sitewatch-env/runtime/reviews'
    for path in sorted(reviews.glob('*/detections.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        value = json.loads(path.read_text())
        if value.get('created_at') == result['created_at'] and value.get('source_sha256') == result['source_sha256']:
            return path.parent
    raise AssertionError('Cannot locate this native downloaded review')


async def download_data(page, context, label):
    async with page.expect_download() as event:
        await page.get_by_role('button', name=label, exact=True).click()
    download = await event.value
    assert urlparse(download.url).hostname in ('127.0.0.1', 'localhost', '::1')
    response = await context.request.get(download.url, timeout=180000)
    assert response.ok
    return await response.body()


async def run(args, report):
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
    from playwright.async_api import async_playwright, expect
    manifest = json.loads((args.project_root/'sitewatch/demo-media.json').read_text())
    assert manifest['schema'] == 'demo-media-v1'
    assert len(manifest['entries']) == 6
    entries = {item['id']: item for item in manifest['entries']}
    assert len(entries) == 6
    assert {'original-1080', 'existing-video', args.video_id, args.photo_id} <= entries.keys()
    assert all(item['recommended_model_id'] in {'sitewatch', 'constructelligence-v03'} for item in entries.values())
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(args.cdp)
        context = await browser.new_context(viewport={'width': 1440, 'height': 1100}, locale='zh-CN', accept_downloads=True)
        async def local_only(route):
            if urlparse(route.request.url).hostname in ('127.0.0.1', 'localhost', '::1'):
                await route.continue_()
            else:
                report['blocked_external'].append(route.request.url)
                await route.abort()
        await context.route('**/*', local_only)
        page = await context.new_page()
        try:
            await page.goto(args.url, wait_until='domcontentloaded')
            await expect(page.get_by_role('heading', name='影像识别与复核')).to_be_visible(timeout=180000)
            await expect(page).to_have_title('水电一局 · 施工视觉AI')
            logo = page.locator('.sd1-logo')
            await expect(logo).to_be_visible()
            assert await logo.evaluate('(img) => img.complete && img.naturalWidth === 344 && img.naturalHeight === 63')
            assert (await logo.get_attribute('src')).startswith('data:image/png;base64,')
            await expect(page.locator('.sd1-step')).to_have_count(3)
            await expect(page.get_by_text('演示环境', exact=True)).to_be_visible()
            await wait_script_idle(page, expect)
            await page.locator('.sd1-masthead').scroll_into_view_if_needed()
            await page.screenshot(path=str(args.output/'00-branded-desktop.png'))
            report['official_logo_embedded_locally'] = True
            report['chinese_branding_and_workflow'] = True
            quality = page.get_by_role('checkbox', name='保留原片画质（较慢）', exact=True)
            await expect(quality).to_be_checked()
            await expect(page.get_by_role('checkbox', name='图像增强', exact=True, include_hidden=True)).to_be_disabled()
            model_container = page.locator('[data-testid="stSelectbox"]').filter(has_text='检测模型')
            model_picker = model_container.get_by_role('combobox')
            await expect(model_container).to_contain_text('自动（按素材推荐）')
            slider = page.locator('[data-testid="stSlider"]').filter(has_text='视频复核起始时长（秒）').get_by_role('slider')
            await wait_script_idle(page, expect)
            for value in range(int(await slider.get_attribute('aria-valuenow')) - 1, 0, -1):
                await slider.press('ArrowLeft')
                await expect(slider).to_have_attribute('aria-valuenow', str(value))
            await expect(slider).to_have_attribute('aria-valuenow', '1')
            await page.get_by_text('清晰演示素材', exact=True).click()
            picker = page.locator('[data-testid="stSelectbox"]').filter(has_text='选择演示素材').get_by_role('combobox')

            async def assert_result_cleared():
                await wait_script_idle(page, expect)
                await expect(page.get_by_role('button', name='下载原始检测 JSON', exact=True)).to_have_count(0)
                await expect(page.get_by_text('Qwen 区域意见：', exact=False)).to_have_count(0)

            async def region_opinion():
                button = page.get_by_role('button', name='复核所选头部', exact=True)
                await expect(button).to_be_enabled(timeout=180000)
                before = await download_data(page, context, '下载原始检测 JSON')
                await button.click()
                await expect(page.get_by_text('Qwen 区域意见：', exact=False)).to_be_visible(timeout=240000)
                assert await download_data(page, context, '下载原始检测 JSON') == before
                return await page.get_by_text('Qwen 区域意见：', exact=False).inner_text()

            async def check_current(entry, label, *, expected_model=None):
                print('Checking '+label, flush=True)
                source = args.project_root/entry['relative_path']
                await expect(page.get_by_text('当前影像：'+source.name, exact=True)).to_be_visible(timeout=180000)
                await assert_result_cleared()
                await wait_script_idle(page, expect)
                await page.get_by_role('button', name='开始识别与复核', exact=True).click()
                await expect(page.get_by_text('识别完成：', exact=False)).to_be_visible(timeout=240000)
                body = await download_data(page, context, '下载原始检测 JSON')
                result = json.loads(body)
                assert result['status'] == 'complete'
                assert result['source_sha256'] == entry['sha256'] == digest(source.read_bytes())
                assert result['settings']['preserve_resolution'] is True
                assert result['settings']['image_enhancement'] is False
                manual_override = expected_model is not None
                expected_model = expected_model or entry.get('recommended_model_id', 'sitewatch')
                assert result['model']['id'] == expected_model
                assert result['settings']['profile'] == entry.get('recommended_profile', 'distant')
                await expect(page.get_by_text('本次检测模型：', exact=False)).to_contain_text(
                    'SiteWatch' if expected_model == 'sitewatch' else 'Constructelligence')
                if entry['media_type'] == 'video':
                    assert result['settings']['max_seconds'] == 1
                    assert len(result['frames']) == 1
                directory = saved_review(args.project_root, result)
                assert body == (directory/'detections.json').read_bytes()
                frame = result['frames'][0]
                if not manual_override:
                    assert frame['detections'], 'Demo must retain real detections'
                if not manual_override and entry['id'] in {args.video_id, args.photo_id}:
                    assert any(d['class_name'].lower() == 'hardhat' for d in frame['detections'])
                elif entry['id'] == 'retained-upload-video':
                    assert any(d['category'] == 'worker' for d in frame['detections'])
                expected_dimensions = frame['source_dimensions_wh']
                if 'width' in entry:
                    assert expected_dimensions == [entry['width'], entry['height']]
                assert frame['detection_dimensions_wh'] == expected_dimensions
                original = await download_data(page, context, '下载原始影像')
                assert digest(original) == entry['sha256']
                input_image = await download_data(page, context, '下载当前输入原图')
                detection_image = await download_data(page, context, '下载当前检测框图')
                assert png_dimensions(input_image) == expected_dimensions
                assert png_dimensions(detection_image) == expected_dimensions
                assert input_image == (directory/frame['input_file']).read_bytes()
                assert detection_image == (directory/frame['review_overlay_file']).read_bytes()
                native = native_first_frame(source, args.project_root)
                downloaded_pixels = cv2.imdecode(np.frombuffer(input_image, np.uint8), cv2.IMREAD_COLOR)
                assert digest(downloaded_pixels.tobytes()) == native['sha256'], 'Input PNG must preserve native decoded pixels'
                assert expected_dimensions == native['dimensions']
                assert await page.get_by_role('radio', name='大图看检测结果', exact=True).is_checked()
                large_image = page.locator('[data-testid="stImage"]').filter(has_text='大图检测结果').locator('img')
                await expect(large_image).to_be_visible()
                large_box = await large_image.bounding_box()
                assert large_box['width'] > 850, large_box
                await large_image.scroll_into_view_if_needed()
                await page.screenshot(path=str(args.output/(label+'-large.png')), full_page=True)
                (args.output/(label+'-detections.json')).write_bytes(body)
                summary = {'id': entry['id'], 'media_type': entry['media_type'], 'source_sha256': entry['sha256'],
                    'model_id': result['model']['id'], 'profile': result['settings']['profile'], 'dimensions': expected_dimensions,
                    'original_download_sha_equal': True, 'input_png_sha256': digest(input_image),
                    'detection_png_sha256': digest(detection_image), 'download_matches_native_saved_bytes': True,
                    'native_source_pixels_equal': True,
                    'source_decoder_opencv': native['opencv'], 'native_pixels_sha256': native['sha256'],
                    'large_view_css_width': large_box['width'], 'review_directory': str(directory),
                    'raw_classes': [d['class_name'] for d in frame['detections']]}
                report['cases'].append(summary)
                return body, large_box['width']

            for index, key in enumerate([args.video_id, args.photo_id]):
                entry = entries[key]
                await picker.click()
                await page.get_by_role('option', name=entry['title'], exact=True).click()
                before, large_width = await check_current(entry, f'{index+1:02d}-{key}')
                if index == 0:
                    await page.get_by_text('左右对照', exact=True).click()
                    await wait_script_idle(page, expect)
                    compared = page.locator('[data-testid="stImage"]').filter(has_text=' · 检测结果').locator('img')
                    await expect(compared).to_be_visible()
                    box = await compared.bounding_box()
                    assert box['width'] < large_width*.75
                    assert await download_data(page, context, '下载原始检测 JSON') == before
                    await compared.scroll_into_view_if_needed()
                    await page.screenshot(path=str(args.output/'03-comparison-preserved.png'), full_page=True)
                    await page.get_by_text('大图看检测结果', exact=True).click()
                    report['quality_switch_previous_qwen'] = await region_opinion()
                    await page.get_by_text('保留原片画质（较慢）', exact=True).click()
                    await expect(quality).not_to_be_checked()
                    await assert_result_cleared()
                    await page.get_by_text('保留原片画质（较慢）', exact=True).click()
                    await expect(quality).to_be_checked()
                    await assert_result_cleared()
                    report['quality_switch_clears_result'] = True
                    report['comparison_changes_display_only'] = True
                    await page.get_by_role('button', name='开始识别与复核', exact=True).click()
                    await expect(page.get_by_text('识别完成：', exact=False)).to_be_visible(timeout=240000)
                    report['asset_switch_previous_qwen'] = await region_opinion()

            # A user choice overrides the asset's recommended model.
            report['model_switch_previous_qwen'] = await region_opinion()
            await model_picker.click()
            await page.get_by_role('option', name='SiteWatch 基线（默认）', exact=True).click()
            await assert_result_cleared()
            report['model_switch_clears_result_and_qwen'] = True
            await check_current(entries[args.photo_id], '05-manual-model', expected_model='sitewatch')
            await model_picker.click()
            await page.get_by_role('option', name='自动（按素材推荐）', exact=True).click()
            await assert_result_cleared()
            report['manual_model_override_verified'] = True

            # Keep the original upload flow and the old video available.
            await page.get_by_text('自己上传', exact=True).click()
            await assert_result_cleared()
            source = args.project_root/'.runtime/vision-media/window-hostivar-0-8.0.mp4'
            await page.locator('input[type=file]').first.set_input_files(
                {'name': source.name, 'mimeType': 'video/mp4', 'buffer': source.read_bytes()})
            old_entry = {'id': 'retained-upload-video', 'relative_path': str(source.relative_to(args.project_root)),
                         'sha256': digest(source.read_bytes()), 'media_type': 'video',
                         'width': entries['existing-video']['width'], 'height': entries['existing-video']['height']}
            await check_current(old_entry, '04-retained-upload')
            report['old_upload_flow_retained'] = True
            report['switching_asset_clears_old_result'] = True
            report['automatic_model_for_upload_is_sitewatch'] = True
            report['manifest_entries'] = len(entries)
            await page.set_viewport_size({'width': 390, 'height': 844})
            collapse = page.locator('[data-testid="stSidebarCollapseButton"] button')
            await page.wait_for_timeout(350)  # Streamlit may already have collapsed offscreen.
            box = await collapse.bounding_box()
            if box and 0 <= box['x'] + box['width']/2 <= 390:
                await collapse.click()
            await page.locator('.sd1-masthead').scroll_into_view_if_needed()
            await expect(logo).to_be_visible()
            await expect(page.locator('.sd1-title')).to_be_visible()
            layout = await page.locator('.sd1-masthead').evaluate('''(node) => {
                const box = node.getBoundingClientRect();
                return {left: box.left, right: box.right, viewport: innerWidth,
                        pageWidth: document.documentElement.scrollWidth};
            }''')
            assert layout['left'] >= 0 and layout['right'] <= layout['viewport'] + 1, layout
            assert layout['pageWidth'] <= layout['viewport'] + 1, layout
            await page.screenshot(path=str(args.output/'06-branded-mobile.png'))
            report['mobile_layout'] = layout
            report['passed'] = True
        except Exception:
            await page.screenshot(path=str(args.output/'failure.png'), full_page=True)
            raise
        finally:
            await context.close()
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8768')
    parser.add_argument('--cdp', default='http://127.0.0.1:9226')
    parser.add_argument('--video-id', default='close-worker')
    parser.add_argument('--photo-id', default='portrait-photo')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new evidence directory')
    args.output.mkdir(parents=True)
    report = {'at': datetime.now(timezone.utc).isoformat(), 'url': args.url, 'passed': False,
              'cases': [], 'blocked_external': [],
              'download_storage': 'Full native downloads hashed and matched in memory; originals remain in the project runtime.'}
    try:
        asyncio.run(run(args, report))
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
