"""Second opinion via the existing local, official Qwen Gradio application."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import time
import threading
import urllib.request
import uuid

# gradio_client 1.13 treats an explicit False as the environment default.
# Set these before its import as well as in the launcher.
os.environ['GRADIO_ANALYTICS_ENABLED'] = 'False'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'

URL = 'http://127.0.0.1:8766'
PROMPT = '请只观察图片中可见的头部。仅回答一个选项：A＝明确佩戴工业安全帽；B＝头发或头皮清楚可见，未见工业安全帽；C＝普通软帽，并非工业安全帽；D＝看不清或无法判断。不要判断法规违规，不要猜测。'
LABELS = {'A': '可见工业安全帽', 'B': '头发或头皮可见，未见工业安全帽',
          'C': '普通软帽，并非工业安全帽', 'D': '看不清或无法判断'}
REPLY_TEXT = {'A': '明确佩戴工业安全帽', 'B': '头发或头皮清楚可见，未见工业安全帽',
              'C': LABELS['C'], 'D': LABELS['D']}
HEAD_LABELS = {'Hardhat': 'helmet', 'NO-Hardhat': 'no_helmet',
               'helmet': 'helmet', 'no-helmet': 'no_helmet',
               'hardhat': 'helmet', 'no-hardhat': 'no_helmet'}
QWEN_SHA = '69d2f15d01e20744dcdb78ed044d06c11592264ae20337aacd0073b3590768d2'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def parse_option(raw):
    clean = html.unescape(re.sub(r'<br\s*/?>', '\n', raw, flags=re.I))
    # Strip only the exact note appended by our existing image backend.
    first = re.sub(r'\s*---\s*本次为图片或文本分析；结论待人工复核。\s*$', '', clean).strip()
    if first in LABELS:
        return first
    # The model sometimes repeats the literal option definition. Accept only
    # an exact frozen option, never an initial letter from ambiguous prose.
    for option, wording in REPLY_TEXT.items():
        if first in (option + '＝' + wording, option + '=' + wording):
            return option
    return None


@lru_cache(maxsize=4)
def checkpoint_digest(path, size, mtime_ns):
    # Stream the large checkpoint; never allocate its entire byte array in RAM.
    file = Path(path)
    with file.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    info = file.stat()
    if info.st_size != size or info.st_mtime_ns != mtime_ns:
        raise ValueError('复核模型权重在校验期间发生变化')
    return digest


def backend_status(project_root):
    """Do not send imagery to an unknown process listening on the review port."""
    root = Path(project_root).resolve()
    try:
        state = json.loads((root / '.runtime/vision-process.json').read_text())
        argv = Path(f'/proc/{state["pid"]}/cmdline').read_bytes().split(b'\0')
        checkpoint = (root / 'downloads/qwen3-vl-4b-nf4').resolve()
        if (str(root / 'vision/web_demo_mm.py').encode() not in argv
                or str(checkpoint).encode() not in argv
                or Path(state.get('model', '')).resolve() != checkpoint
                or not owns_review_listener(state['pid'], argv)):
            raise ValueError('本地复核端口未匹配已验证的 Qwen4B 服务')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + '/config', timeout=2) as response:
            if response.status != 200:
                raise ValueError('本地复核页面尚未就绪')
        weight = checkpoint / 'model.safetensors'
        info = weight.stat()
        digest = checkpoint_digest(str(weight), info.st_size, info.st_mtime_ns)
        if digest != QWEN_SHA:
            raise ValueError('复核模型权重与已验证版本不符')
        return {'ready': True, 'url': URL, 'model': 'Qwen3-VL-4B-Instruct local NF4',
                'checkpoint': str(checkpoint), 'pid': state['pid'],
                'weight_sha256': digest, 'weight_size': info.st_size,
                'weight_mtime_ns': info.st_mtime_ns}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ready': False, 'url': URL, 'error': str(exc)}


def owns_review_listener(pid, argv, proc_root=Path('/proc')):
    """Bind the declared process to the exact loopback listening socket."""
    def argument(name):
        try:
            return argv[argv.index(name.encode()) + 1]
        except (ValueError, IndexError):
            return None

    if argument('--server-port') != b'8766' or argument('--server-name') != b'127.0.0.1':
        return False
    process = Path(proc_root) / str(pid)
    sockets = set()
    for fd in (process / 'fd').iterdir():
        try:
            target = fd.readlink().as_posix()
        except OSError:
            continue  # A request socket can close while enumerating.
        if target.startswith('socket:[') and target.endswith(']'):
            sockets.add(target[8:-1])
    for line in (process / 'net/tcp').read_text().splitlines()[1:]:
        fields = line.split()
        if (len(fields) > 9 and fields[1] == '0100007F:223E'
                and fields[3] == '0A' and fields[9] in sockets):
            return True
    return False


def cancel_job(client, job):
    """A stalled cancellation request must not postpone the failed UI result."""
    client.httpx_kwargs['timeout'] = 2.0

    def cancel():
        try:
            job.cancel()
        except Exception:
            pass  # Best effort; the failed attempt remains the authoritative result.

    threading.Thread(target=cancel, daemon=True, name='head-review-cancel').start()


def classify_crop(crop_path, project_root):
    """Reuse native upload and submit APIs, each call with a fresh chat session."""
    from gradio_client import Client, handle_file
    backend = backend_status(project_root)
    if not backend['ready']:
        raise RuntimeError('本地复核模型未就绪，请先运行视觉AI启动脚本。' + backend.get('error', ''))
    started = time.perf_counter()
    # Keep the SDK's native executor default: a request, SSE reader, response
    # waiter and cancellation watcher share it. Artificially limiting it to
    # one or two workers deadlocks before inference.
    client = Client(URL, hf_token=False, verbose=False,
                    download_files=False, analytics_enabled=False,
                    httpx_kwargs={'trust_env': False, 'timeout': 90.0})
    try:
        upload_job = client.submit(history=[], file=handle_file(str(Path(crop_path).resolve())), api_name='/add_file')
        try:
            uploaded = upload_job.result(timeout=30)
        except TimeoutError:
            cancel_job(client, upload_job)
            raise RuntimeError('区域上传超时，未生成复核结论')
        job = client.submit(history=uploaded, text=PROMPT, api_name='/submit_and_predict')
        try:
            response = job.result(timeout=120)
        except TimeoutError:
            cancel_job(client, job)
            raise RuntimeError('区域复核超时，原检测结果保留，请稍后重试')
        history = response[0]
        raw = history[-1][1]
        if not isinstance(raw, str):
            raise ValueError('复核服务未返回文本，不能解析为已确认结果')
        option = parse_option(raw)
        return {'backend': backend, 'raw_answer': raw, 'option': option,
                'label': LABELS.get(option, '回答格式未确认，请查看原文'),
                'classification_confidence': None,
                'elapsed_seconds': time.perf_counter() - started,
                'prompt': PROMPT, 'prompt_sha256': hashlib.sha256(PROMPT.encode()).hexdigest(),
                'api': ['/add_file', '/submit_and_predict'],
                'api_history': history, 'fresh_session': True}
    finally:
        client.close()


def head_indices(frame):
    return [i for i, item in enumerate(frame['detections']) if item['class_name'] in HEAD_LABELS]


def region_location(review_dir, frame_position, detection_index):
    return Path(review_dir) / 'head-reviews' / f'frame-{frame_position:06d}-detection-{detection_index:04d}'


def latest_region_review(review_dir, frame_position, detection_index):
    path = region_location(review_dir, frame_position, detection_index) / 'latest.json'
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def crop_box(bbox, width, height):
    if len(bbox) != 4 or not all(math.isfinite(float(v)) for v in bbox):
        raise ValueError('检测框坐标无效')
    x1, y1, x2, y2 = map(float, bbox)
    if x2 <= x1 or y2 <= y1:
        raise ValueError('检测框为空')
    if x2 <= 0 or y2 <= 0 or x1 >= width or y1 >= height:
        raise ValueError('检测框超出画面')
    dx, dy = (x2 - x1) * .2, (y2 - y1) * .2
    clipped = [min(width, max(0, int(x1-dx))), min(height, max(0, int(y1-dy))),
               min(width, max(0, int(x2+dx+1))), min(height, max(0, int(y2+dy+1)))]
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        raise ValueError('裁剪区域超出画面')
    return clipped


def review_head_region(review_dir, frame_position, detection_index, project_root):
    """Retain the source detector result; save crop and independent VLM opinion."""
    import cv2
    directory = Path(review_dir).resolve()
    original = json.loads((directory / 'detections.json').read_text())
    if original['status'] != 'complete':
        raise ValueError('仅允许复核已完成检测的画面')
    if not 0 <= frame_position < len(original['frames']):
        raise ValueError('采样画面索引无效')
    frame = original['frames'][frame_position]
    if detection_index not in head_indices(frame):
        raise ValueError('当前选框不是直接头部类别，不能判断是否戴帽')
    detection = frame['detections'][detection_index]
    image_path = (directory / frame['input_file']).resolve()
    if not image_path.is_relative_to(directory):
        raise ValueError('采样画面不属于本次复核目录')
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError('原始采样图无法读取')
    bbox = detection.get('bbox_xyxy') or detection['bbox']
    clipped = crop_box(bbox, image.shape[1], image.shape[0])
    crop = image[clipped[1]:clipped[3], clipped[0]:clipped[2]]
    if crop.size == 0:
        raise ValueError('裁剪区域超出画面')
    destination = region_location(directory, frame_position, detection_index)
    destination.mkdir(parents=True, exist_ok=True)
    attempts = destination / 'attempts'
    attempts.mkdir(exist_ok=True)
    attempt = attempts / (datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
    attempt.mkdir()
    crop_path = attempt / 'crop.png'
    if not cv2.imwrite(str(crop_path), crop):
        raise OSError('无法保存裁剪原图')
    record = {'schema': 'ppe-head-second-opinion-v1', 'status': 'processing',
              'at': datetime.now(timezone.utc).isoformat(),
              'source_sha256': original['source_sha256'], 'frame_position': frame_position,
              'frame_index': frame['frame_index'], 'timestamp_seconds': frame['timestamp_seconds'],
              'input_file': frame['input_file'], 'input_sha256': sha(image_path),
              'input_basis': 'Saved unannotated decoded frame shown in this review; its dimensions and SHA are recorded. No overlays or expected answers are sent.',
              'detector_model': original['model'], 'detector_detection': detection,
              'crop_file': str(crop_path.relative_to(directory)), 'crop_sha256': sha(crop_path),
              'crop_box_in_input': clipped, 'padding_fraction': .2,
              'notice': '第二意见不改写原检测类别或分数；模型分歧待人工复核，不是法规违规结论。'}
    try:
        opinion = classify_crop(crop_path, project_root)
        record['opinion'] = opinion
        model_label = HEAD_LABELS[detection['class_name']]
        option = opinion['option']
        record['comparison'] = ('uncertain' if option in (None, 'D') else
                                'agree' if (option == 'A') == (model_label == 'helmet') else 'disagree')
        record['status'] = 'complete'
    except Exception as exc:
        record['status'] = 'failed'
        record['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        atomic_json(attempt / 'review.json', record)
        atomic_json(destination / 'latest.json', record)
    return record
