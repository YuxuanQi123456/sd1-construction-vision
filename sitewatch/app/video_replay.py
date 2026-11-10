"""Streaming, real per-frame inference and H.264 replay; no annotation interpolation."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import cv2

from cv_pipeline.enhancement import enhance
from review_evidence import resize_long_edge
from tracking import ByteTrackEvidence


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def existing_replay(review_dir):
    root = Path(review_dir)
    manifest = root / 'video-replay/replay.json'
    if not manifest.is_file():
        return None
    item = json.loads(manifest.read_text())
    if item.get('status') != 'complete' or item.get('detections_sha256') != _sha(root / 'detections.json'):
        return None
    original = json.loads((root / 'detections.json').read_text())
    source = (root / original['source_file']).resolve()
    if (not source.is_relative_to(root.resolve()) or not source.is_file()
            or item.get('source_sha256') != original['source_sha256']
            or _sha(source) != original['source_sha256']):
        return None
    for field, sha_field in [('video_file', 'video_sha256'), ('frames_file', 'frames_sha256')]:
        path = (root / item[field]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or _sha(path) != item[sha_field]:
            return None
    return item


def build_video_replay(review_dir, detector, *, progress=None):
    """Generate every frame in the sampled review's analysis range, sequentially."""
    from imageio_ffmpeg import get_ffmpeg_exe

    root = Path(review_dir).resolve()
    raw_record = (root / 'detections.json').read_bytes()
    record = json.loads(raw_record)
    if record.get('status') != 'complete' or record.get('media_type') != 'video':
        raise ValueError('连续回放需要已完成检测的视频任务')
    for key in ['id', 'sha256', 'inference_imgsz', 'profile']:
        if detector.provenance.get(key) != record['model'].get(key):
            raise ValueError('当前模型与本次检测不一致，请重新检测后生成回放')
    if detector.conf_threshold != record['settings']['confidence']:
        raise ValueError('当前阈值与本次检测不一致')
    ready = existing_replay(root)
    if ready:
        return ready
    source = (root / record['source_file']).resolve()
    if not source.is_relative_to(root) or _sha(source) != record['source_sha256']:
        raise ValueError('回放原视频校验失败')
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        cap.release()
        raise ValueError('不能解码回放原视频')
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not math.isfinite(fps) or fps <= 0 or count <= 0 or width <= 0 or height <= 0:
        cap.release()
        raise ValueError('回放视频帧率或尺寸无效')
    limit = min(count, math.ceil(record['settings']['max_seconds'] * fps))
    tracker = ByteTrackEvidence(sample_seconds=1 / fps)
    started = time.perf_counter()
    output = root / 'video-replay'
    # The temporary folder is outside this evidence package, so partial videos
    # cannot be exported as a finished replay by a parallel page session.
    with tempfile.TemporaryDirectory(prefix='.visual-replay-', dir=root.parent) as temporary:
        stage = Path(temporary)
        movie, frames_path = stage / 'replay.mp4', stage / 'frames.jsonl'
        command = [get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
                   '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', str(fps),
                   '-i', 'pipe:0', '-an', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
                   '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency', '-crf', '18', '-threads', '2',
                   '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(movie)]
        processed = 0
        try:
            with (stage / 'encoder.log').open('wb') as log, frames_path.open('w', encoding='utf-8') as evidence:
                encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
                try:
                    for index in range(limit):
                        ok, frame = cap.read()
                        if not ok:
                            raise ValueError(f'回放在源帧 {index} 提前解码结束，需要 {limit} 帧')
                        image = frame if record['settings']['preserve_resolution'] else resize_long_edge(frame)
                        image = enhance(image) if record['settings']['image_enhancement'] else image
                        detections, _, inference_ms = detector.detect_frame(image)
                        ih, iw = image.shape[:2]
                        values = [asdict(item) for item in detections]
                        tracks = tracker.update(values, [iw, ih])
                        by_detection = {item['detection_index']: item['track_id'] for item in tracks}
                        display = frame.copy()
                        sx, sy = width / iw, height / ih
                        for number, detection in enumerate(detections):
                            x1, y1, x2, y2 = detection.bbox
                            box = (round(x1 * sx), round(y1 * sy), round(x2 * sx), round(y2 * sy))
                            color = (60, 215, 80) if detection.category == 'worker' else (255, 195, 40)
                            cv2.rectangle(display, box[:2], box[2:], color, 1)
                            # Tiny targets stay unobscured; their complete scores
                            # and IDs remain in the per-frame JSONL evidence.
                            if box[2] - box[0] >= 35 and box[3] - box[1] >= 45:
                                label = by_detection.get(number, detection.class_name) + f' {detection.confidence:.2f}'
                                cv2.putText(display, label, (box[0], max(12, box[1] - 4)), cv2.FONT_HERSHEY_SIMPLEX, .42, color, 1, cv2.LINE_AA)
                        cv2.putText(display, f'Analyzed replay | {index/fps:.2f}s | frame {index}', (12, 24), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 0), 3, cv2.LINE_AA)
                        cv2.putText(display, f'Analyzed replay | {index/fps:.2f}s | frame {index}', (12, 24), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1, cv2.LINE_AA)
                        evidence.write(json.dumps({'frame_index': index, 'timestamp_seconds': index / fps,
                                                   'detection_dimensions_wh': [iw, ih], 'detections': values,
                                                   'tracks': tracks, 'inference_ms': inference_ms}, ensure_ascii=False) + '\n')
                        encoder.stdin.write(display.tobytes())
                        processed += 1
                        if progress and (index % max(1, round(fps)) == 0 or processed == limit):
                            progress(processed, limit)
                    encoder.stdin.close()
                    if encoder.wait(timeout=30) != 0:
                        raise ValueError('回放视频编码失败：' + (stage / 'encoder.log').read_text()[-400:])
                finally:
                    if encoder.poll() is None:
                        encoder.kill()
                        encoder.wait()
                    if encoder.stdin and not encoder.stdin.closed:
                        encoder.stdin.close()
            probe = cv2.VideoCapture(str(movie))
            try:
                if not probe.isOpened() or int(probe.get(cv2.CAP_PROP_FRAME_COUNT)) != processed:
                    raise ValueError('回放成片帧数校验失败')
            finally:
                probe.release()
            info = {'schema': 'visual-video-replay-v1', 'status': 'complete',
                    'at': datetime.now(timezone.utc).isoformat(), 'model': record['model'],
                    'settings': record['settings'], 'source_sha256': record['source_sha256'],
                    'detections_sha256': hashlib.sha256(raw_record).hexdigest(),
                    'video_file': 'video-replay/replay.mp4', 'video_sha256': _sha(movie),
                    'frames_file': 'video-replay/frames.jsonl', 'frames_sha256': _sha(frames_path),
                    'decoded_frame_count': processed, 'fps': fps, 'source_dimensions_wh': [width, height],
                    'output_dimensions_wh': [width + width % 2, height + height % 2],
                    'duration_seconds': processed / fps, 'elapsed_seconds': time.perf_counter() - started,
                    'timestamp_basis': 'decoded frame index / container FPS', 'audio_in_replay': False,
                    'notice': '本地逐帧真实推理的已分析回放；轨迹ID仅在此回放内有效。MP4叠框另行编码，原视频保持原字节。'}
            (stage / 'replay.json').write_text(json.dumps(info, ensure_ascii=False, indent=2))
            if _sha(root / 'detections.json') != info['detections_sha256'] or _sha(source) != info['source_sha256']:
                raise ValueError('处理期间原证据变化，未发布回放')
            # Keep an existing valid output intact. Another session may have
            # completed it while this session was generating the same task.
            if output.exists():
                ready = existing_replay(root)
                if ready:
                    return ready
                raise ValueError('已存在不完整回放目录，请保留记录并重新建立检测任务')
            stage.replace(output)
            return info
        finally:
            cap.release()
