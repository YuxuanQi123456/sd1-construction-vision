"""Exercise the configured review backend without changing the detector.

Uses real API credits when the openai provider has a key; choose a new output path.
"""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[1])
    media = parser.add_mutually_exclusive_group(required=True)
    media.add_argument('--crop', type=Path)
    media.add_argument('--image', type=Path, help='Run the real detector and verify nested region evidence')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output file; existing evidence is never overwritten')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runtime = args.project_root / '.runtime/ppe-v08-probe'
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / 'ultralytics').mkdir(exist_ok=True)
    (runtime / 'matplotlib').mkdir(exist_ok=True)
    os.environ.update(CUDA_VISIBLE_DEVICES='', YOLO_CONFIG_DIR=str(runtime / 'ultralytics'),
                      MPLCONFIGDIR=str(runtime / 'matplotlib'))
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'app'))
    from region_review import classify_crop
    record = {'crop': str(args.crop) if args.crop else None,
              'image': str(args.image) if args.image else None, 'passed': False}
    try:
        if args.image:
            from region_integrity import check_real_region
            record['result'] = check_real_region(args.image, args.project_root,
                                                 args.output.with_name(args.output.stem + '-artifacts'))
        else:
            record['result'] = classify_crop(args.crop, args.project_root)
        record['passed'] = True
    except Exception as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
