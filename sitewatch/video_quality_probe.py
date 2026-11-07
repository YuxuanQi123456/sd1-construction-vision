"""Fixed native YOLO comparison on a saved, unannotated review frame set.

This diagnostic never changes the running service, predictions, or source media.
The two approximate worker boxes are observations, not an accuracy benchmark.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def iou(a, b):
    width = max(0., min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0., min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    union = (a[2]-a[0]) * (a[3]-a[1]) + (b[2]-b[0]) * (b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--source-review', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--coco-lock', type=Path, required=True)
    args = parser.parse_args()
    root, source, output = args.project_root.resolve(), args.source_review.resolve(), args.output.resolve()
    if output.exists():
        parser.error('Choose a fresh output directory; failed experiments are retained')
    output.mkdir(parents=True)
    runtime = output / '.runtime'
    for folder in ['ultralytics', 'matplotlib']:
        (runtime / folder).mkdir(parents=True, exist_ok=True)
    os.environ.update(CUDA_VISIBLE_DEVICES='', YOLO_AUTOINSTALL='false', HF_HUB_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', GRADIO_ANALYTICS_ENABLED='False',
                      YOLO_CONFIG_DIR=str(runtime / 'ultralytics'), MPLCONFIGDIR=str(runtime / 'matplotlib'))
    import cv2
    import torch
    import ultralytics
    from ultralytics import YOLO
    from ultralytics.utils import YAML
    torch.set_num_threads(2)
    manifest_path = root / 'sitewatch/model-candidates.json'
    manifest = json.loads(manifest_path.read_text())
    coco = json.loads(args.coco_lock.read_text())
    assert coco['verified'] is True
    coco_yaml = Path(ultralytics.__file__).parent / 'cfg/datasets/coco.yaml'
    coco_names = YAML.load(str(coco_yaml))['names']
    coco_spec = {**coco, 'weights': coco['weight'],
                 'expected_names': [coco_names[i] for i in range(80)], 'classes': {'person': 0}}
    specs = [manifest['models'][0], coco_spec, *manifest['models'][1:]]
    assert [s['id'] for s in specs] == ['sitewatch', 'ultralytics-yolov8n-coco',
                                      'yolo11n', 'safetyvision-v2', 'constructelligence-v03']
    source_record_path = source / 'detections.json'
    original_record_sha = sha(source_record_path)
    source_record = json.loads(source_record_path.read_text())
    frames = source_record['frames']
    assert len(frames) == 8
    assert [f['timestamp_seconds'] for f in frames] == list(range(8))
    assert source_record['media_type'] == 'video' and source_record['status'] == 'complete'
    rough_workers = [[118, 247, 142, 317], [150, 272, 190, 347]]
    inputs = []
    for frame in frames:
        path = (source / frame['input_file']).resolve()
        assert path.is_relative_to(source)
        inputs.append({'frame_index': frame['frame_index'], 'timestamp_seconds': frame['timestamp_seconds'],
                       'path': str(path), 'sha256': sha(path)})
    report = {'at': datetime.now(timezone.utc).isoformat(), 'passed': False, 'runs': [],
              'command_argv': sys.argv, 'source_review': str(source),
              'source_record_sha256_before': original_record_sha,
              'source_video_sha256': source_record['source_sha256'],
              'input_basis': 'Same saved unannotated JPEGs for all models; not byte-identical to original uncompressed decoder arrays.',
              'inputs': inputs, 'manifest_sha256': sha(manifest_path),
              'coco_lock_sha256': sha(args.coco_lock), 'coco_names_yaml_sha256': sha(coco_yaml),
              'versions': {p: importlib.metadata.version(p) for p in ['torch', 'ultralytics', 'opencv-python']},
              'fixed': {'confidence': .4, 'imgsz_values': [640, 1280], 'iou': .7, 'device': 'cpu',
                        'threads': 2, 'enhancement': False, 'rect': True, 'max_det': 300},
              'predeclared_rough_observation': {'timestamp_seconds': 7, 'workers_xyxy': rough_workers,
                   'scope': 'Approximate visible trackside workers only, not formal GT or accuracy metric. Cabin occupancy is unknown; no helmet GT.'}}
    write_json(output / 'report.json', report)
    started = time.perf_counter()
    try:
        for spec in specs:
            weights = root / spec['weights']
            digest = sha(weights)
            assert digest == spec['sha256'], spec['id']
            if 'bytes' in spec:
                assert weights.stat().st_size == spec['bytes']
            model = YOLO(str(weights))
            names = dict(model.names)
            assert [names[i] for i in range(len(names))] == spec['expected_names'], spec['id']
            assert next(model.model.parameters()).device.type == 'cpu'
            person_id = spec['classes']['person']
            canonical = {v: k for k, v in spec['classes'].items()}
            for imgsz in [640, 1280]:
                case_dir = output / f'{spec["id"]}-{imgsz}'
                case_dir.mkdir()
                case = {'model_id': spec['id'], 'weight_sha256': digest, 'weights': str(weights),
                        'model_source': spec['source'], 'model_revision': spec['revision'],
                        'actual_names': names, 'model_overrides_before_predict': dict(model.overrides),
                        'requested_imgsz': imgsz, 'confidence': .4, 'frames': []}
                shapes = []
                hook = model.model.register_forward_pre_hook(
                    lambda module, positional: shapes.append(list(positional[0].shape)))
                try:
                    for frame, input_info in zip(frames, inputs):
                        image = cv2.imread(input_info['path'])
                        assert image is not None and list(image.shape[:2]) == [540, 960]
                        shapes.clear()
                        start = time.perf_counter()
                        result = model.predict(image, conf=.4, imgsz=imgsz, iou=.7, max_det=300,
                                               device='cpu', rect=True, verbose=False)[0]
                        elapsed = time.perf_counter() - start
                        raw = []
                        for box in result.boxes:
                            class_id = int(box.cls[0])
                            raw.append({'class_id': class_id, 'class_name': names[class_id],
                                        'canonical_class': canonical.get(class_id),
                                        'confidence': float(box.conf[0]), 'bbox_xyxy': box.xyxy[0].tolist()})
                        item = {'frame_index': frame['frame_index'], 'timestamp_seconds': frame['timestamp_seconds'],
                                'input_sha256': input_info['sha256'], 'original_shape_hw': list(result.orig_shape),
                                'predictor_imgsz': list(model.predictor.imgsz),
                                'forward_tensor_shapes': list(shapes), 'elapsed_seconds': elapsed,
                                'native_speed_ms': result.speed, 'detections': raw}
                        assert shapes and shapes[-1][0:2] == [1, 3]
                        if frame['timestamp_seconds'] in [0, 4, 7]:
                            name = f'frame-{frame["frame_index"]:06d}-overlay.jpg'
                            assert cv2.imwrite(str(case_dir / name), result.plot())
                            item['native_overlay'] = name
                        if frame['timestamp_seconds'] == 7:
                            people = [d for d in raw if d['class_id'] == person_id]
                            item['rough_worker_best_iou'] = [max((iou(b, d['bbox_xyxy']) for d in people), default=0.)
                                                            for b in rough_workers]
                        case['frames'].append(item)
                        write_json(case_dir / 'predictions.json', case)
                finally:
                    hook.remove()
                summary = {'model_id': spec['id'], 'imgsz': imgsz,
                           'raw_class_counts': dict(Counter(d['class_name'] for f in case['frames'] for d in f['detections'])),
                           'rough_worker_best_iou_at_7s': case['frames'][-1]['rough_worker_best_iou'],
                           'prediction_json': str((case_dir / 'predictions.json').relative_to(output)),
                           'elapsed_seconds': sum(f['elapsed_seconds'] for f in case['frames'])}
                report['runs'].append(summary)
                write_json(output / 'report.json', report)
                print(json.dumps(summary, ensure_ascii=False), flush=True)
            del model
        assert sha(source_record_path) == original_record_sha
        for item in inputs:
            assert sha(item['path']) == item['sha256']
        report['source_record_sha256_after'] = sha(source_record_path)
        report['source_evidence_unchanged'] = True
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        report['total_seconds'] = time.perf_counter() - started
        report['exit_code'] = 0 if report['passed'] else 1
        write_json(output / 'report.json', report)


if __name__ == '__main__':
    main()
