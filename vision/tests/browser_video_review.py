"""Real browser acceptance for the approved Qwen3-VL video review demo.

Without --run this performs local source checks only: no browser or HTTP calls.
With --run, use an isolated context in an existing CDP browser, or explicitly
select a local Chromium installation. It never installs/starts the application.
Model answers are captured, never supplied by this test. Semantic accuracy needs
separate visual review of the saved source frames and actual responses.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APP = Path('/mnt/e/workspace/云枢/水电一局演示Demo')
QUESTION = '请描述画面中实际可见的人员、机械和作业；指出有画面依据的疑似风险及大致时间，无法确认的情况请明确说明。'
FOLLOWUP = '请复核你刚才提到的风险：哪些具体画面支持它？能否确认有人位于吊物正下方？看不清或不能确认的请明确说明，不要补充画面外事实。'
NOTE = '本轮实际抽样时间'

# Observe clones of the real frontend's fetch responses. Requests, bodies and
# responses delivered to the application are unchanged; no extra model calls.
OBSERVE_FETCH = r"""(() => {
  const original = window.fetch;
  window.__v02Streams = [];
  window.__v02Stage = 'initial';
  window.fetch = async function(...args) {
    const response = await original.apply(this, args);
    if (new URL(response.url, location.href).pathname.endsWith('/queue/data')) {
      const entry = {url: response.url, stage: window.__v02Stage, chunks: [], error: null};
      window.__v02Streams.push(entry);
      const reader = response.clone().body.getReader();
      const decoder = new TextDecoder();
      (async () => {
        try {
          while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            entry.chunks.push(decoder.decode(value, {stream: true}));
          }
          entry.chunks.push(decoder.decode());
        } catch (error) { entry.error = String(error); }
      })();
    }
    return response;
  };
})();"""


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def stream_events(streams):
    events = []
    for index, stream in enumerate(streams):
        for line in ''.join(stream['chunks']).splitlines():
            if line.startswith('data:'):
                try:
                    events.append({'stream': index, 'event': json.loads(line[5:])})
                except json.JSONDecodeError:
                    pass  # A currently incomplete final line is read on the next poll.
    return events


def all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from all_strings(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from all_strings(child)


def repetition_diagnostics(text):
    """Describe actual repetition for review; this is not a factuality score."""
    sentences = [part.strip(' *#-') for part in re.split(r'[。！？\n]+', text)]
    counts = Counter(part for part in sentences if len(part) >= 8)
    compact = re.sub(r'\s+', '', text)
    grams = Counter(compact[index:index + 12] for index in range(max(0, len(compact) - 11)))
    return {'characters': len(text),
            'repeated_sentences': [{'text': part, 'count': count} for part, count in counts.most_common() if count > 1],
            'most_repeated_12_character_spans': [{'text': part, 'count': count} for part, count in grams.most_common(5) if count >= 3],
            'ends_with_sentence_punctuation': bool(re.search(r'[。！？.!?][”"）)]?$', text)),
            'interpretation': 'Screening evidence only; inspect actual response and video before assigning a business verdict.'}


async def run(args, report):
    from playwright.async_api import async_playwright, expect

    manifest = json.loads((args.app_root / 'vision/config/samples.json').read_text())
    samples = {row['id']: row for row in manifest}
    selected = [samples[args.first], samples[args.second], samples[args.third]]
    report['samples'] = [{**row, 'sha256': digest(args.app_root / 'downloads/vision-samples' / row['file'])} for row in selected]
    report['playwright_version'] = importlib.metadata.version('playwright')
    report['browser_mode'] = 'existing CDP browser, isolated new context' if args.cdp_url else 'explicit local Chromium'
    stage = {'name': 'initial'}
    context = None
    page = None
    os.environ['NO_PROXY'] = '127.0.0.1,localhost,::1'
    os.environ['no_proxy'] = os.environ['NO_PROXY']
    if args.browser_path:
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(args.browser_path)

    def check(name, detail):
        report['checks'].append({'name': name, 'passed': True, 'detail': detail, 'at': stamp()})
        write_json(args.output / 'report.json', report)
        print(json.dumps({'check': name, 'passed': True}, ensure_ascii=False), flush=True)

    async with async_playwright() as playwright:
        if args.cdp_url:
            browser = await playwright.chromium.connect_over_cdp(args.cdp_url)
        else:
            browser_env = os.environ.copy()
            if args.browser_path:
                browser_env['PLAYWRIGHT_BROWSERS_PATH'] = str(args.browser_path)
                os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(args.browser_path)
            if args.library_path:
                browser_env['LD_LIBRARY_PATH'] = str(args.library_path)
            if args.font_dir:
                fontconfig = args.output / 'fontconfig.xml'
                fontconfig.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig>'
                                      '<include ignore_missing="yes">/etc/fonts/fonts.conf</include><dir>'
                                      + html.escape(str(args.font_dir.resolve())) + '</dir><cachedir>'
                                      + html.escape(str(args.output / 'font-cache')) + '</cachedir></fontconfig>')
                browser_env['FONTCONFIG_FILE'] = str(fontconfig.resolve())
            browser = await playwright.chromium.launch(headless=True, args=['--no-proxy-server'], env=browser_env)
        try:
            context = await browser.new_context(viewport={'width': 1920, 'height': 1080}, locale='zh-CN', reduced_motion='reduce')

            async def local_only(route):
                if urlparse(route.request.url).hostname not in ('127.0.0.1', 'localhost', '::1'):
                    report['external_blocked'].append({'url': route.request.url, 'stage': stage['name']})
                    await route.abort('blockedbyclient')
                else:
                    await route.continue_()

            await context.route('**/*', local_only)
            await context.add_init_script(OBSERVE_FETCH)
            page = await context.new_page()
            page.on('request', lambda req: report['requests'].append({'method': req.method, 'url': req.url, 'type': req.resource_type, 'stage': stage['name']}))
            page.on('response', lambda res: report['http_errors'].append({'status': res.status, 'url': res.url, 'stage': stage['name']}) if res.status >= 400 else None)
            page.on('console', lambda msg: report['console_errors'].append({'text': msg.text, 'stage': stage['name']}) if msg.type == 'error' else None)
            page.on('pageerror', lambda error: report['page_errors'].append({'text': str(error), 'stage': stage['name']}))
            page.on('requestfailed', lambda req: report['request_errors'].append({'url': req.url, 'failure': req.failure, 'stage': stage['name']}))

            async def set_stage(name):
                stage['name'] = name
                await page.evaluate('(name) => window.__v02Stage = name', name)
                print(json.dumps({'stage': name, 'at': stamp()}, ensure_ascii=False), flush=True)

            async def screenshot(name):
                await page.screenshot(path=str(args.output / (name + '.png')), full_page=True, animations='disabled')

            async def capture_streams():
                streams = await page.evaluate('window.__v02Streams || []')
                write_json(args.output / 'raw-gradio-streams.json', streams)
                events = stream_events(streams)
                write_json(args.output / 'gradio-events.json', events)
                return events

            async def clear():
                await page.get_by_role('button', name=re.compile('Clear History')).click()
                await expect(page.locator('[data-testid="bot"]')).to_have_count(0, timeout=60000)
                await expect(page.locator('[role="log"] video')).to_have_count(0, timeout=60000)

            async def load_sample(sample):
                combo = page.get_by_role('listbox', name='选择公开实拍样例', exact=True)
                await combo.click()
                await page.get_by_role('option', name=sample['title'], exact=True).click()
                await page.get_by_role('button', name='载入样例（开启新会话）', exact=True).click()
                await expect(page.locator('[role="log"] video')).to_have_count(1, timeout=60000)
                await expect(page.locator('[data-testid="bot"]')).to_have_count(0, timeout=60000)
                await expect(page.get_by_text(re.compile('没有权威违规标签'))).to_be_visible()
                await page.wait_for_function('''filename => {
                    const video = document.querySelector('[role="log"] video');
                    return video && video.readyState >= 2 && (video.currentSrc || video.src).includes(filename);
                }''', arg=sample['file'], timeout=60000)
                video = page.locator('[role="log"] video').first
                await video.evaluate('(v) => v.pause()')
                src = await video.evaluate('(v) => v.currentSrc || v.src')
                assert sample['file'] in src, (sample['file'], src)
                if args.check_video_layout:
                    layout = await video.evaluate('''v => {
                        const box=v.getBoundingClientRect(), log=v.closest('[role="log"]'), parent=log.getBoundingClientRect();
                        return {video_height:box.height, video_top:box.top, video_bottom:box.bottom,
                            chat_height:log.clientHeight, chat_top:parent.top, chat_bottom:parent.bottom,
                            object_fit:getComputedStyle(v).objectFit, natural_width:v.videoWidth, natural_height:v.videoHeight};
                    }''')
                    report.setdefault('video_layout', {})[sample['id']] = layout
                    assert layout['object_fit'] == 'contain', layout
                    assert layout['video_height'] <= 320.5, layout
                    assert layout['video_height'] <= layout['chat_height'], layout
                    assert layout['video_top'] >= layout['chat_top'] - 2 and layout['video_bottom'] <= layout['chat_bottom'] + 2, layout
                    await screenshot('layout-' + sample['id'])
                return src

            async def source_frames(sample, times):
                target = args.output / 'frames'
                target.mkdir(exist_ok=True)
                video = page.locator('[role="log"] video').first
                records = []
                for index, seconds in enumerate(times):
                    info = await video.evaluate('''async (v, seconds) => {
                      v.pause();
                      if (v.readyState < 2) await new Promise((resolve, reject) => {
                        const timeout = setTimeout(() => reject(new Error('video metadata timeout')), 15000);
                        v.addEventListener('loadeddata', () => {clearTimeout(timeout);resolve();}, {once:true});
                        v.addEventListener('error', () => {clearTimeout(timeout);reject(new Error('video decode error'));}, {once:true});
                      });
                      if (!Number.isFinite(v.duration)) throw new Error('video duration unavailable');
                      const desired = Math.min(seconds, Math.max(0, v.duration - 0.05));
                      if (Math.abs(v.currentTime - desired) > 0.001) {
                        await new Promise((resolve, reject) => {
                          const timeout = setTimeout(() => reject(new Error('video seek timeout')), 15000);
                          v.addEventListener('seeked', () => {clearTimeout(timeout);resolve();}, {once:true});
                          v.currentTime = desired;
                        });
                      }
                      const canvas = document.createElement('canvas');
                      canvas.width = v.videoWidth; canvas.height = v.videoHeight;
                      if (!canvas.width || !canvas.height) throw new Error('decoded video frame unavailable');
                      const ctx = canvas.getContext('2d'); ctx.drawImage(v, 0, 0);
                      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                      let min=255, max=0;
                      for (let i=0; i<pixels.length; i+=4000) {min=Math.min(min,pixels[i]);max=Math.max(max,pixels[i]);}
                      return {current_time_s:v.currentTime, duration_s:v.duration, width:v.videoWidth, height:v.videoHeight,
                              decoded_pixel_range:[min,max], png:canvas.toDataURL('image/png')};
                    }''', seconds)
                    filename = f'{sample["id"]}-{index:02d}-{seconds:.2f}s.png'
                    (target / filename).write_bytes(base64.b64decode(info.pop('png').split(',', 1)[1]))
                    assert info['decoded_pixel_range'][1] - info['decoded_pixel_range'][0] > 10, 'Unexpected blank decoded frame in these known nonblank construction samples'
                    records.append({'requested_time_s': seconds, **info, 'file': 'frames/' + filename,
                                    'capture': 'Full decoded original-video frame from browser canvas; avoids chat viewport clipping'})
                report['source_frames'][sample['id']] = records
                if len(records) > 1:
                    # A labelled HTML gallery preserves all saved originals; no model
                    # or image synthesis is used to build this review contact sheet.
                    figures = []
                    for record in records:
                        figures.append('<figure><img src="' + html.escape(record['file'], quote=True) + '"><figcaption>'
                                       + f"{record['current_time_s']:.2f}s" + '</figcaption></figure>')
                    filename = 'contact-' + sample['id'] + '.html'
                    (args.output / filename).write_text('<html lang="zh-CN"><meta charset="utf-8"><style>'
                        'body{margin:16px;background:#eff3f6;color:#153047;font:15px Microsoft YaHei,sans-serif}'
                        'h1{font-size:18px}main{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}'
                        'figure{margin:0;background:white}img{width:100%;display:block}figcaption{padding:8px}'
                        '</style><h1>' + html.escape(sample['title']) + ' · 实际回答所列采样位置</h1><main>'
                        + ''.join(figures) + '</main><p>原始公开视频的浏览器解码帧；时间为近似复核位置。完整分辨率见 frames/。</p></html>')
                    report.setdefault('frame_galleries', {})[sample['id']] = filename

            async def ask(sample, question, label, expected_count):
                await set_stage(label)
                started = time.monotonic()
                await page.locator('textarea').first.fill(question)
                await page.get_by_role('button', name=re.compile('Submit')).click()
                last_progress = 0
                answer = ''
                while time.monotonic() - started < args.answer_timeout:
                    bots = page.locator('[data-testid="bot"]')
                    if await bots.count() == expected_count:
                        answer = await bots.last.inner_text()
                        if NOTE in answer:
                            break
                    alerts = await page.get_by_role('alert').all_inner_texts()
                    if any('模型运行失败' in text or '生成超时' in text or '上下文预算已满' in text for text in alerts):
                        raise AssertionError(f'Actual model failure: {alerts}')
                    elapsed = time.monotonic() - started
                    if elapsed - last_progress >= 30:
                        print(json.dumps({'stage': label, 'waiting_seconds': round(elapsed), 'visible_chars': len(answer)}, ensure_ascii=False), flush=True)
                        last_progress = elapsed
                    await asyncio.sleep(1)
                else:
                    raise TimeoutError(f'{label}: no completed model response within {args.answer_timeout}s; visible output: {answer}')
                model_text = answer.split(NOTE)[0].strip().rstrip('—-*').strip()
                assert model_text and re.search(r'[\u4e00-\u9fff]', model_text), 'No nonempty Chinese model response (technical condition only)'
                assert model_text != question, 'Response only echoes the question'
                times = [float(value) for value in re.findall(r'(\d+(?:\.\d+)?)s', answer.split(NOTE, 1)[1])]
                assert len(times) == args.expected_frames and times == sorted(times), times
                raw_html = await bots.last.inner_html()
                row = {'sample': sample['id'], 'question': question, 'displayed_answer': answer, 'displayed_html': raw_html,
                       'elapsed_seconds': round(time.monotonic() - started, 3), 'actual_sampling_times_s': times,
                       'output_diagnostics': repetition_diagnostics(model_text),
                       'business_accuracy': 'Not inferred from nonempty text; visual review pending'}
                report['answers'][label] = row
                write_json(args.output / (label + '-answer.json'), row)
                await screenshot(label)
                await capture_streams()
                check(label, {'sample': sample['id'], 'answer_characters': len(model_text), 'sampled_frames': len(times),
                              'elapsed_seconds': row['elapsed_seconds'], 'scope': 'Real generation and UI flow only; not a correctness score'})
                return row

            await page.goto(args.base_url, wait_until='domcontentloaded')
            await expect(page.get_by_role('heading', name='施工视频 AI 隐患审查')).to_be_visible(timeout=60000)
            report['served_config'] = await page.evaluate('''() => ({version:window.gradio_config?.version,
                dependencies:(window.gradio_config?.dependencies || []).map(x => ({id:x.id, api_name:x.api_name, inputs:x.inputs, outputs:x.outputs}))})''')
            await screenshot('01-initial')

            if args.ui_only:
                for sample in selected:
                    await set_stage('ui_only_' + sample['id'])
                    await load_sample(sample)
                    await source_frames(sample, [0.0])
                    check('load_decode_' + sample['id'], 'Actual sample selection, local video playback metadata and full decoded first frame; no model submit.')
                await clear()
                await capture_streams()
                report['technical_exit_code'] = 0
                report['run_scope'] = 'UI/media checks only; no model requests submitted'
                return

            await set_stage('empty_question_error')
            await page.locator('textarea').first.fill('')
            await page.get_by_role('button', name=re.compile('Submit')).click()
            await expect(page.get_by_role('alert').filter(has_text='请先输入要核查的问题')).to_be_visible(timeout=60000)
            await screenshot('02-empty-question-error')
            check('empty_question_visible_error', 'Real Gradio validation message was visible; no fake response was inserted.')
            for close in await page.get_by_test_id('toast-close').all():
                await close.click()

            await set_stage('missing_media_error')
            await page.locator('textarea').first.fill(QUESTION)
            await page.get_by_role('button', name=re.compile('Submit')).click()
            await expect(page.get_by_role('alert').filter(has_text='请先上传一张图片或一个视频')).to_be_visible(timeout=60000)
            await expect(page.locator('[data-testid="user"]')).to_have_count(0)
            await expect(page.locator('[data-testid="bot"]')).to_have_count(0)
            await screenshot('02b-missing-media-error')
            check('missing_media_visible_error', 'No-media submit produced a real visible error and left the actual conversation empty.')
            for close in await page.get_by_test_id('toast-close').all():
                await close.click()

            await set_stage('actual_video_upload')
            sample_path = args.app_root / 'downloads/vision-samples' / selected[0]['file']
            await page.locator('input[type=file]').first.set_input_files({'name': sample_path.name, 'mimeType': 'video/webm', 'buffer': sample_path.read_bytes()})
            await expect(page.locator('[role="log"] video')).to_have_count(1, timeout=60000)
            await screenshot('03-uploaded-video')
            check('actual_video_upload', {'file': sample_path.name, 'bytes': sample_path.stat().st_size})
            # Intentionally do not clear between the invalid submit and this real generation.
            await ask(selected[0], '请简要描述画面中实际可见的人员、机械与作业，无法确认的内容请明确说明。', '03b-upload-recovery-answer', 1)
            check('missing_media_upload_recovery', 'After the no-media error, uploading a real video allowed actual generation without clearing or reloading the session.')
            await clear()

            await set_stage('first_sample_loaded')
            first_src = await load_sample(selected[0])
            await screenshot('04-first-sample')
            first = await ask(selected[0], QUESTION, '05-first-answer', 1)
            await source_frames(selected[0], first['actual_sampling_times_s'])
            await ask(selected[0], FOLLOWUP, '06-same-video-followup', 2)
            assert await page.locator('[role="log"] video').first.evaluate('(v) => v.currentSrc || v.src') == first_src
            check('same_video_followup_context', 'One unchanged video remained in the actual conversation with both answers.')

            await set_stage('second_sample_loaded')
            second_src = await load_sample(selected[1])
            assert second_src != first_src
            await screenshot('07-second-sample-new-session')
            check('switch_video_resets_history', 'Changing to the second sample removed prior bot messages and changed the video URL.')
            second = await ask(selected[1], QUESTION, '08-second-answer', 1)
            await source_frames(selected[1], second['actual_sampling_times_s'])

            await set_stage('third_sample_loaded')
            third_src = await load_sample(selected[2])
            assert third_src not in (first_src, second_src)
            await screenshot('09-third-sample-new-session')
            check('third_video_resets_history', 'Switching to the third real sample removed earlier bot messages and changed the video URL.')
            third = await ask(selected[2], QUESTION, '10-third-answer', 1)
            await source_frames(selected[2], third['actual_sampling_times_s'])
            await set_stage('clear_final')
            await clear()
            await screenshot('11-cleared-history')
            check('clear_history', 'Actual conversation contains no bot messages or videos after Clear History.')

            events = await capture_streams()
            completed_generations = [row for row in events if row['event'].get('msg') == 'process_completed'
                                     and row['event'].get('success') is True
                                     and any(NOTE in text for text in all_strings(row['event'].get('output')))]
            final_answers = [text for row in completed_generations for text in all_strings(row['event'].get('output')) if NOTE in text]
            assert len(completed_generations) == 5, 'Did not capture exactly five actual completed generations from Gradio SSE'
            write_json(args.output / 'raw-completed-model-outputs.json', final_answers)
            check('raw_model_output_evidence', {'completed_generations': len(completed_generations), 'completed_output_strings': len(final_answers), 'capture': 'Unmodified clones of actual Gradio SSE fetch responses'})
            assert not report['page_errors'], report['page_errors']
            report['technical_exit_code'] = 0
            report['business_accuracy_status'] = 'Pending visual comparison; nonempty replies do not establish hazard-detection accuracy.'
        except Exception:
            if page:
                try:
                    await screenshot('failure')
                    await capture_streams()
                    report['failure_page_text'] = await page.locator('body').inner_text()
                    report['failure_controls'] = await page.locator('input,button,textarea,[role]').evaluate_all('''nodes => nodes.map(node => ({
                        tag:node.tagName,role:node.getAttribute('role'),label:node.getAttribute('aria-label'),
                        type:node.getAttribute('type'),text:node.innerText?.slice(0,100)}))''')
                except Exception as capture_error:
                    report['failure_capture_error'] = str(capture_error)
            raise
        finally:
            if context:
                await context.close()  # Only the isolated context created by this test.
            if not args.cdp_url:
                await browser.close()  # Never close a remotely attached browser/user windows.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Actually connect and issue model requests; use only after coordinator READY')
    parser.add_argument('--ui-only', action='store_true', help='With --run, only exercise selectors/sample loading/video decoding; no model submissions')
    parser.add_argument('--check-video-layout', action='store_true', help='Require the complete video box to fit inside the chatbot viewport with object-fit:contain')
    parser.add_argument('--base-url', default='http://127.0.0.1:8766')
    parser.add_argument('--cdp-url', help='Attach to an existing browser, e.g. http://127.0.0.1:9226')
    parser.add_argument('--app-root', type=Path, default=DEFAULT_APP)
    parser.add_argument('--browser-path', type=Path)
    parser.add_argument('--library-path', type=Path)
    parser.add_argument('--font-dir', type=Path)
    parser.add_argument('--first', default='florenc')
    parser.add_argument('--second', default='excavator-loading')
    parser.add_argument('--third', default='hostivar')
    parser.add_argument('--answer-timeout', type=int, default=1200)
    parser.add_argument('--expected-frames', type=int, default=16)
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence/V02/browser')
    args = parser.parse_args()
    if urlparse(args.base_url).hostname not in ('127.0.0.1', 'localhost', '::1'):
        parser.error('The application must be local.')
    if args.cdp_url and urlparse(args.cdp_url).hostname not in ('127.0.0.1', 'localhost', '::1'):
        parser.error('The CDP browser must be local.')
    if len({args.first, args.second, args.third}) != 3:
        parser.error('Use three distinct videos.')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'started_at': stamp(), 'command': sys.argv, 'python': sys.version.split()[0],
              'base_url': args.base_url, 'cdp_url': args.cdp_url, 'checks': [], 'answers': {}, 'source_frames': {},
              'requests': [], 'http_errors': [], 'console_errors': [], 'page_errors': [], 'request_errors': [],
              'external_blocked': [], 'technical_exit_code': None, 'business_accuracy_status': 'Not assessed',
              'source_sha256': {str(path.relative_to(args.app_root)): digest(path) for path in
                                [args.app_root / 'vision/web_demo_mm.py', args.app_root / 'vision/local_support.py',
                                 args.app_root / 'vision/config/samples.json']}}
    if not args.run:
        source = (args.app_root / 'vision/web_demo_mm.py').read_text()
        assert all(text in source for text in ['submit_and_predict', '载入样例（开启新会话）', 'Clear History', '请先输入要核查的问题'])
        report['status'] = 'LOCAL_SOURCE_CHECK_ONLY; no HTTP, browser or model requests executed'
        report['finished_at'] = stamp()
        write_json(args.output / 'source-check.json', report)
        print(report['status'])
        return
    try:
        asyncio.run(run(args, report))
    except Exception as error:
        report['technical_exit_code'] = 1
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        report['finished_at'] = stamp()
        write_json(args.output / 'report.json', report)
    print(json.dumps({'technical_exit_code': report['technical_exit_code'], 'checks': len(report['checks']),
                      'business_accuracy_status': report['business_accuracy_status'], 'report': str(args.output / 'report.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
