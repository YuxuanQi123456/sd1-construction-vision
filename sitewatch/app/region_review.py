"""Independent head-region second opinion through the configured GPT API."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import uuid

from review_api import (api_backend_status, load_review_config, request_image_opinion,
                        review_backend_snapshot)

PROMPT = '请只观察图片中可见的头部。仅回答一个选项：A＝明确佩戴工业安全帽；B＝头发或头皮清楚可见，未见工业安全帽；C＝普通软帽，并非工业安全帽；D＝看不清或无法判断。不要判断法规违规，不要猜测。'
LABELS = {'A': '可见工业安全帽', 'B': '头发或头皮可见，未见工业安全帽',
          'C': '普通软帽，并非工业安全帽', 'D': '看不清或无法判断'}
REPLY_TEXT = {'A': '明确佩戴工业安全帽', 'B': '头发或头皮清楚可见，未见工业安全帽',
              'C': LABELS['C'], 'D': LABELS['D']}
HEAD_LABELS = {'Hardhat': 'helmet', 'NO-Hardhat': 'no_helmet',
               'helmet': 'helmet', 'no-helmet': 'no_helmet',
               'hardhat': 'helmet', 'no-hardhat': 'no_helmet'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def parse_option(raw):
    first = raw.strip()
    if first in LABELS:
        return first
    # The model sometimes repeats the literal option definition. Accept only
    # an exact frozen option, never an initial letter from ambiguous prose.
    for option, wording in REPLY_TEXT.items():
        if first in (option + '＝' + wording, option + '=' + wording):
            return option
    return None


def backend_status(project_root):
    """Report API configuration without a network request."""
    return api_backend_status(project_root)


def classify_crop(crop_path, project_root):
    """Request a GPT opinion using one validated configuration snapshot."""
    config = load_review_config(project_root)
    return _classify_crop_configured(crop_path, project_root, config)


def _classify_crop_configured(crop_path, project_root, config):
    result = request_image_opinion(crop_path, project_root, PROMPT, _config=config)
    option = parse_option(result['raw_answer'])
    return {**result, 'option': option,
            'label': LABELS.get(option, '回答格式未确认，请查看原文'),
            'classification_confidence': None, 'prompt': PROMPT,
            'prompt_sha256': hashlib.sha256(PROMPT.encode()).hexdigest()}


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
              'notice': '第二意见不改写原检测类别或分数；模型分歧待人工复核，不是法规违规结论。',
              'prompt': PROMPT, 'prompt_sha256': hashlib.sha256(PROMPT.encode()).hexdigest(),
              'classification_confidence': None}
    try:
        # One configuration snapshot supplies both request provenance and transport.
        config = load_review_config(project_root)
        record['request_backend'] = review_backend_snapshot(config, project_root)
        atomic_json(attempt / 'review.json', record)
        opinion = _classify_crop_configured(crop_path, project_root, config)
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
