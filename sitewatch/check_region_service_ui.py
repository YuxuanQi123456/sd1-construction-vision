"""Exercise real Qwen stop/cold-start/recovery through the integrated PPE page."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from browser_verify import native_download, upload_and_review


async def run(args, record):
    from playwright.async_api import async_playwright, expect
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
    async def manage(*arguments):
        process = await asyncio.create_subprocess_exec(
            'python3', str(args.project_root / 'vision/scripts/manage.py'), *arguments,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        result = {'arguments': arguments, 'exit_code': process.returncode,
                  'stdout': stdout.decode(), 'stderr': stderr.decode()}
        record.setdefault('commands', []).append(result)
        assert process.returncode == 0, result
        return result

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(args.cdp)
        context = await browser.new_context(viewport={'width': 1440, 'height': 1100}, accept_downloads=True)
        page = await context.new_page()
        stopped = False
        try:
            await page.goto(args.url)
            await expect(page.get_by_role('heading', name='影像识别与复核')).to_be_visible(timeout=120000)
            await page.get_by_text("自己上传", exact=True).click()
            await upload_and_review(page, args.project_root / 'downloads/vision-samples/niosh-runway-worker.jpg', expect)
            button = page.get_by_role('button', name='复核所选头部', exact=True)
            await expect(button).to_be_enabled(timeout=120000)
            before = await native_download(page, context, '下载原始检测 JSON', args.output / 'before.json')
            toggle = page.get_by_text('显示全部25类（含人员、设备及可能误检）', exact=True)
            await manage('stop')
            stopped = True
            await toggle.click()
            await expect(button).to_be_disabled()
            await expect(page.get_by_text('区域复核模型未就绪，请先运行', exact=False)).to_be_visible()
            after_stop = await native_download(page, context, '下载原始检测 JSON', args.output / 'while-stopped.json')
            assert before == after_stop
            await page.screenshot(path=str(args.output / '01-stopped-disabled.png'), full_page=True)
            record['unavailable_disabled_original_export_preserved'] = True
            started = time.monotonic()
            await manage('start')
            stopped = False
            await toggle.click()
            await expect(button).to_be_disabled()
            record['cold_loading_disabled'] = True
            deadline = time.monotonic() + 480
            while time.monotonic() < deadline:
                try:
                    response = await context.request.get('http://127.0.0.1:8766/config', timeout=2000)
                    if response.ok and 'components' in await response.json():
                        break
                except Exception:
                    pass
                await asyncio.sleep(2)
            else:
                raise TimeoutError('Owned model did not recover within 480 seconds')
            record['cold_start_seconds'] = time.monotonic() - started
            await toggle.click()
            await expect(button).to_be_enabled(timeout=120000)
            await button.click()
            await expect(page.get_by_text('Qwen 区域意见：可见工业安全帽', exact=True)).to_be_visible(timeout=180000)
            after = await native_download(page, context, '下载原始检测 JSON', args.output / 'after-recovery.json')
            assert before == after
            await native_download(page, context, '下载完整证据（原文件 / 检测框 / JSON）', args.output / 'recovered-evidence.zip')
            await page.screenshot(path=str(args.output / '02-recovered-real-opinion.png'), full_page=True)
            record['real_generation_after_restart'] = True
            record['original_detector_bytes_unchanged'] = True
            record['passed'] = True
        finally:
            if stopped:
                await manage('start')
            await context.close()
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8767')
    parser.add_argument('--cdp', default='http://127.0.0.1:9226')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new evidence directory')
    args.output.mkdir(parents=True)
    record = {'at': datetime.now(timezone.utc).isoformat(), 'passed': False}
    try:
        asyncio.run(run(args, record))
    except Exception as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        (args.output / 'report.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
