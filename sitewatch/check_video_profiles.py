"""Verify the real dual-model adapter on the user's fixed video; no mocked AI."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--source-review', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new evidence directory')
    args.output.mkdir(parents=True)
    runtime = args.project_root / '.runtime/sitewatch-env/runtime'
    os.environ.update(CUDA_VISIBLE_DEVICES='', SITEWATCH_PROJECT_ROOT=str(args.project_root),
                      YOLO_CONFIG_DIR=str(runtime/'ultralytics'), MPLCONFIGDIR=str(runtime/'matplotlib'))
    sys.path.insert(0, str(Path(__file__).resolve().parent/'app'))
    from cv_pipeline.detection import Detector, _iou
    from review_evidence import review_file, evidence_zip
    original_bytes = (args.source_review/'detections.json').read_bytes()
    original = json.loads(original_bytes)
    source = args.source_review/original['source_file']
    record = {'at': datetime.now(timezone.utc).isoformat(), 'passed': False,
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'profiles': []}
    try:
        assert record['source_sha256'] == original['source_sha256']
        for profile in ['standard', 'distant']:
            detector = Detector(profile=profile)
            directory = args.output/profile
            result = review_file(source, detector, directory, max_seconds=8)
            assert len(result['frames']) == 8
            frame7 = next(frame for frame in result['frames'] if frame['timestamp_seconds'] == 7)
            people = [d for d in frame7['detections'] if d['category'] == 'worker']
            # These human rough regions were declared before prediction (V09/PLAN).
            rough = [[118,247,142,317], [150,272,190,347]]
            ious = [max((_iou(box, d['bbox']) for d in people), default=0) for box in rough]
            if profile == 'standard':
                assert detector.person is None
                assert json.loads(json.dumps([f['detections'] for f in result['frames']])) == [f['detections'] for f in original['frames']]
            else:
                assert min(ious) > .5, 'Two visible trackside workers remain missed'
                assert result['settings']['inference_imgsz'] == 1280
                assert result['settings']['person_companion'] is True
                assert all(d['class_name'] == 'person' and d['class_id'] == 0
                           for f in result['frames'] for d in f['model_branches']['ultralytics-yolov8n-coco'])
                assert any(d['class_name'] == 'Hardhat' for d in frame7['detections'])
            package = evidence_zip(directory)
            with zipfile.ZipFile(package) as archive:
                assert archive.read('detections.json') == (directory/'detections.json').read_bytes()
                for frame in result['frames']:
                    assert frame['review_overlay_file'] in archive.namelist()
            record['profiles'].append({'profile': profile, 'rough_worker_iou_at_7s': ious,
                'frame7_detections': frame7['detections'], 'zip_verified': True,
                'elapsed_seconds': result['elapsed_seconds'],
                'helmet_notice': 'Direct candidate at visible head; no authoritative helmet or violation ground truth.'})
        assert (args.source_review/'detections.json').read_bytes() == original_bytes
        record['old_review_unchanged'] = True
        record['passed'] = True
    except Exception as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        (args.output/'report.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
