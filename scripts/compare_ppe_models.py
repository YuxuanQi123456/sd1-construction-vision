"""Compare fixed, openly licensed pretrained models on the same four real photos."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--models', type=Path)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    manifest = args.models or root / 'sitewatch/model-candidates.json'
    if args.output.exists():
        parser.error('Use a new evidence directory; old predictions are never overwritten.')
    args.output.mkdir(parents=True)
    runtime = root / '.runtime/ppe-v07'
    for folder in [runtime, runtime / 'ultralytics', runtime / 'matplotlib']:
        folder.mkdir(parents=True, exist_ok=True)
    os.environ.update(CUDA_VISIBLE_DEVICES='', YOLO_CONFIG_DIR=str(runtime / 'ultralytics'),
                      MPLCONFIGDIR=str(runtime / 'matplotlib'), YOLO_AUTOINSTALL='false')
    import cv2
    import torch
    from ultralytics import YOLO
    sys.path.insert(0, str(root / 'sitewatch/app'))
    from review_evidence import resize_long_edge, source_provenance
    torch.set_num_threads(2)
    model_specs = json.loads(manifest.read_text())['models']
    filenames = ['niosh-runway-worker.jpg', 'working-the-grinder.jpg',
                 'plasterer-original.jpg', 'bricklayer.jpg']
    samples = []
    report = {'at': datetime.now(timezone.utc).isoformat(), 'manifest_sha256': sha(manifest),
              'device': 'cpu', 'settings': {'conf': 0.4, 'imgsz': args.imgsz, 'iou': 0.7,
                  'max_long_edge': 1280, 'enhancement': False, 'threads': 2},
              'note': 'Same original photos, fixed before candidate predictions. Raw classes retained; no legal violation labels or accuracy percentages.',
              'models': [], 'inputs': []}
    for filename in filenames:
        path = root / 'downloads/vision-samples' / filename
        frame = cv2.imread(str(path))
        if frame is None:
            raise ValueError(f'Cannot read original photo: {path}')
        image = resize_long_edge(frame)
        media_dir = args.output / 'inputs' / path.stem
        media_dir.mkdir(parents=True)
        (media_dir / 'original.jpg').write_bytes(path.read_bytes())
        assert cv2.imwrite(str(media_dir / 'input.jpg'), image)
        attribution = source_provenance(sha(path))
        assert attribution['registered'], path
        (media_dir / 'source-provenance.json').write_text(json.dumps(attribution, ensure_ascii=False, indent=2)+'\n')
        samples.append((filename, image))
        report['inputs'].append({'file': filename, 'sha256': sha(path),
                                 'source_dimensions_wh': [frame.shape[1], frame.shape[0]],
                                 'inference_dimensions_wh': [image.shape[1], image.shape[0]]})
    for spec in model_specs:
        output = args.output / spec['id']
        output.mkdir()
        entry = {'id': spec['id'], 'sha256': spec['sha256'], 'reviews': [], 'passed': False}
        report['models'].append(entry)
        try:
            weights = root / spec['weights']
            if sha(weights) != spec['sha256']:
                raise ValueError(f'Weight SHA mismatch: {spec["id"]}')
            model = YOLO(str(weights))
            names = [model.names[i] for i in range(len(model.names))]
            if names != spec['expected_names']:
                raise ValueError(f'Unexpected actual model names: {names}')
            entry['actual_names'] = names
            inverse = {v: k for k, v in spec['classes'].items()}
            for filename, image in samples:
                started = time.perf_counter()
                result = model.predict(image, conf=0.4, imgsz=args.imgsz, iou=0.7,
                                       device='cpu', verbose=False, augment=False)[0]
                elapsed = time.perf_counter() - started
                detections = []
                for box in result.boxes:
                    cid = int(box.cls[0])
                    detections.append({'class_id': cid, 'class_name': names[cid],
                        'canonical_class': inverse.get(cid), 'confidence': float(box.conf[0]),
                        'bbox_xyxy': [float(x) for x in box.xyxy[0].tolist()]})
                review = {'file': filename, 'elapsed_seconds': elapsed, 'detections': detections}
                entry['reviews'].append(review)
                (output / f'{Path(filename).stem}.json').write_text(json.dumps(review, ensure_ascii=False, indent=2)+'\n')
                assert cv2.imwrite(str(output / f'{Path(filename).stem}-overlay.jpg'), result.plot())
                print(json.dumps({'model': spec['id'], 'file': filename,
                    'elapsed_seconds': round(elapsed, 3),
                    'classes': [d['class_name'] for d in detections]}, ensure_ascii=False), flush=True)
            entry['passed'] = True
            del model
        except Exception as exc:
            entry['error'] = f'{type(exc).__name__}: {exc}'
            print(json.dumps({'model': spec['id'], 'error': entry['error']}, ensure_ascii=False), flush=True)
        finally:
            (args.output / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    if not all(item['passed'] for item in report['models']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
