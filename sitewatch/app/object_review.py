"""Original-pixel crops and independent human decisions for any detected object."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import uuid

import cv2


PARTS = {'whole': '整个对象', 'head': '头部参考区域', 'torso': '上身参考区域'}
TARGET_STATES = {'pending': '待人工复核', 'confirmed': '确认目标', 'dismissed': '排除误检', 'uncertain': '看不清'}
PPE_STATES = {'pending': '尚未复核', 'visible': '可见已佩戴', 'suspected_missing': '疑似未佩戴', 'uncertain': '无法判断'}


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _atomic(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_bytes(raw)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _contained(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('复核原文件不可用')
    return path


def crop_target(review_dir, frame_position, detection_index=None, manual_box=None, part='whole'):
    """Crop original decoded pixels; person subregions are geometry references only."""
    root = Path(review_dir)
    record = _json(root / 'detections.json')
    if type(frame_position) is not int or not 0 <= frame_position < len(record['frames']):
        raise ValueError('帧位置无效')
    frame = record['frames'][frame_position]
    if detection_index is not None:
        if type(detection_index) is not int or not 0 <= detection_index < len(frame['detections']):
            raise ValueError('检测对象无效')
        detection = frame['detections'][detection_index]
        box = detection.get('bbox_xyxy', detection['bbox'])
        origin = 'detector'
    else:
        detection = None
        box = manual_box
        origin = 'manual_region'
    if not isinstance(box, (list, tuple)) or len(box) != 4 or not all(math.isfinite(float(x)) for x in box):
        raise ValueError('请先选择对象或在原图上拖出复核区域')
    x1, y1, x2, y2 = map(float, box)
    dw, dh = frame['detection_dimensions_wh']
    if not 0 <= x1 < x2 <= dw or not 0 <= y1 < y2 <= dh:
        # Some detector boxes reach fractionally outside a frame; clip them.
        x1, y1, x2, y2 = max(0., x1), max(0., y1), min(dw, x2), min(dh, y2)
        if x2 <= x1 or y2 <= y1:
            raise ValueError('复核区域超出画面')
    target_box = [x1, y1, x2, y2]
    if part not in PARTS:
        raise ValueError('局部区域类型无效')
    if part == 'head':
        y2 = y1 + (y2 - y1) * .35
    elif part == 'torso':
        height = y2 - y1
        y1, y2 = y1 + height * .2, y1 + height * .7
    source = _contained(root, record['source_file'])
    if hashlib.sha256(source.read_bytes()).hexdigest() != record['source_sha256']:
        raise ValueError('原始影像校验失败，请保留证据并重新检测')
    if record['media_type'] == 'image':
        pixels = cv2.imread(str(source))
    else:
        cap = cv2.VideoCapture(str(source))
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame['frame_index'])
            ok, pixels = cap.read()
            if not ok:
                raise ValueError('不能读取原视频对应帧')
        finally:
            cap.release()
    if pixels is None:
        raise ValueError('原始画面不能解码')
    sh, sw = pixels.shape[:2]
    sx, sy = sw / dw, sh / dh
    # Preserve integer pixel coverage, and never interpolate before cropping.
    coords = [max(0, math.floor(x1 * sx)), max(0, math.floor(y1 * sy)),
              min(sw, math.ceil(x2 * sx)), min(sh, math.ceil(y2 * sy))]
    crop = pixels[coords[1]:coords[3], coords[0]:coords[2]].copy()
    if not crop.size:
        raise ValueError('裁剪区域为空')
    ok, encoded = cv2.imencode('.png', crop)
    if not ok:
        raise ValueError('原图裁剪保存失败')
    raw = encoded.tobytes()
    identity = {'frame_position': frame_position, 'frame_index': frame['frame_index'],
                'detection_index': detection_index, 'origin': origin, 'bbox_detection_xyxy': target_box}
    target_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    evidence = {**identity, 'target_id': target_id, 'timestamp_seconds': frame['timestamp_seconds'],
                'part': part, 'part_label': PARTS[part], 'original_crop_xyxy': coords,
                'original_frame_dimensions_wh': [sw, sh], 'crop_dimensions_wh': [crop.shape[1], crop.shape[0]],
                'crop_sha256': hashlib.sha256(raw).hexdigest(), 'source_sha256': record['source_sha256'],
                'detector_label': detection['class_name'] if detection else None,
                'detector_confidence': detection['confidence'] if detection else None,
                'subregion_notice': '头部/上身参考仅按人员框位置裁取，不是装备识别结论。'}
    return raw, evidence


@contextmanager
def _locked(root):
    path = root / 'object-reviews'
    path.mkdir(exist_ok=True)
    with (path / '.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield path
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_object_reviews(review_dir):
    path = Path(review_dir) / 'object-reviews/decisions.json'
    return _json(path) if path.is_file() else {'schema': 'visual-object-review-v1', 'decisions': {}, 'history': []}


def save_object_decision(review_dir, evidence, *, target_state, helmet_state, vest_state, note=''):
    if target_state not in TARGET_STATES or helmet_state not in PPE_STATES or vest_state not in PPE_STATES:
        raise ValueError('人工复核状态无效')
    if not isinstance(note, str) or len(note) > 1000:
        raise ValueError('备注最多1000字')
    # Re-derive pixels from original evidence, rather than trusting a UI crop.
    raw, current = crop_target(review_dir, evidence['frame_position'], evidence['detection_index'],
                               evidence['bbox_detection_xyxy'] if evidence['origin'] == 'manual_region' else None,
                               evidence['part'])
    if current != evidence:
        raise ValueError('原始证据已变化，请重新选择对象')
    now = datetime.now(timezone.utc).isoformat()
    record = {'at': now, 'evidence': current, 'target_state': target_state, 'helmet_state': helmet_state,
              'vest_state': vest_state, 'note': note, 'judgement_source': 'human',
              'notice': '人工复核独立记录，不修改检测器原框、类别或分数。'}
    root = Path(review_dir)
    with _locked(root) as folder:
        payload = load_object_reviews(root)
        key = current['target_id']
        record['crop_file'] = f"object-reviews/crops/{key}-{current['part']}.png"
        _atomic(root / record['crop_file'], raw)
        payload['decisions'][key] = record
        payload['history'].append(record)
        _atomic(folder / 'decisions.json', json.dumps(payload, ensure_ascii=False, indent=2).encode())
    return record
