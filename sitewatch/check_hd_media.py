"""Real inference on native public assets; prove pixel-preserving frame saves."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    import cv2
    import numpy as np
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.artifacts.exists() or args.report.exists():
        parser.error('Use fresh report and artifact paths')
    args.artifacts.mkdir(parents=True)
    runtime = args.project_root/'.runtime/sitewatch-env/runtime'
    os.environ.update(CUDA_VISIBLE_DEVICES='', SITEWATCH_PROJECT_ROOT=str(args.project_root),
                      YOLO_CONFIG_DIR=str(runtime/'ultralytics'), MPLCONFIGDIR=str(runtime/'matplotlib'))
    sys.path.insert(0, str(Path(__file__).resolve().parent/'app'))
    from cv_pipeline.detection import Detector
    from review_evidence import review_file
    manifest = json.loads((args.project_root/'sitewatch/demo-media.json').read_text())
    detectors = {}
    report = {'passed': False, 'entries': [], 'no_weight_training': True,
              'input_policy': 'Native decoded pixels preserved; model still applies its explicit inference size internally.'}
    try:
        for entry in manifest['entries']:
            path = args.project_root/entry['relative_path']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']
            profile = entry['recommended_profile']
            model_id = entry.get('recommended_model_id', 'sitewatch')
            key = (model_id, profile)
            if key not in detectors:
                detectors[key] = Detector(model_id=model_id, profile=profile)
            output = args.artifacts/entry['id']
            result = review_file(path, detectors[key], output, max_seconds=1, preserve_resolution=True)
            frame = result['frames'][0]
            if entry['media_type'] == 'video':
                cap = cv2.VideoCapture(str(path))
                ok, original = cap.read()
                cap.release()
                assert ok
            else:
                original = cv2.imread(str(path))
            saved = cv2.imread(str(output/frame['input_file']))
            assert np.array_equal(original, saved), 'Saved source pixels changed'
            assert frame['source_dimensions_wh'] == frame['detection_dimensions_wh'] == [entry['width'],entry['height']]
            assert frame['input_file'].endswith('.png') and frame['review_overlay_file'].endswith('.png')
            assert hashlib.sha256((output/result['source_file']).read_bytes()).hexdigest() == entry['sha256']
            assert result['source_provenance']['registered'] is True
            item = {'id': entry['id'], 'width': entry['width'], 'height': entry['height'],
                'source_bytes_identical': True, 'saved_png_pixels_identical_to_decoder': True,
                'artifact_dir': str(output), 'profile': profile, 'model_id': model_id,
                'elapsed_seconds': result['elapsed_seconds'],
                'model_input_size': detectors[key].inference_imgsz,
                'detections': [{'class':d['class_name'], 'confidence':d['confidence'], 'source':d['source']} for d in frame['detections']]}
            report['entries'].append(item)
            print(json.dumps(item,ensure_ascii=False),flush=True)
        try:
            review_file(path, detectors[key], args.artifacts/'invalid-enhancement-control',
                        preserve_resolution=True, do_enhance=True)
        except ValueError:
            report['preservation_rejects_enhancement'] = True
        else:
            raise AssertionError('Enhancement must not silently change preserved pixels')
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
