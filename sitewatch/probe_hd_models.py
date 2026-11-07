"""Compare existing pinned PPE weights on fixed native first frames for demo presets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a fresh report')
    root = args.project_root
    os.environ.update(CUDA_VISIBLE_DEVICES='', YOLO_AUTOINSTALL='false', HF_HUB_OFFLINE='1',
                      YOLO_CONFIG_DIR=str(root/'.runtime/sitewatch-env/runtime/ultralytics'),
                      MPLCONFIGDIR=str(root/'.runtime/sitewatch-env/runtime/matplotlib'))
    import cv2
    import torch
    from ultralytics import YOLO
    torch.set_num_threads(2)
    media = json.loads((root/'sitewatch/demo-media.json').read_text())['entries'][:4]
    specs = json.loads((root/'sitewatch/model-candidates.json').read_text())['models']
    report = {'passed':False,'input_policy':'Same native decoded first frame; conf .4; CPU; no enhancement.', 'runs':[]}
    try:
        for spec in specs:
            weight = root/spec['weights']
            assert hashlib.sha256(weight.read_bytes()).hexdigest() == spec['sha256']
            model = YOLO(str(weight))
            assert [model.names[i] for i in range(len(model.names))] == spec['expected_names']
            for entry in media:
                path = root/entry['relative_path']
                if entry['media_type'] == 'video':
                    cap = cv2.VideoCapture(str(path)); ok,image = cap.read();cap.release();assert ok
                else:
                    image = cv2.imread(str(path));assert image is not None
                for size in [640,1280]:
                    started=time.perf_counter()
                    result=model.predict(image,conf=.4,imgsz=size,iou=.7,device='cpu',verbose=False)[0]
                    item={'model_id':spec['id'],'asset_id':entry['id'],'imgsz':size,'elapsed_seconds':time.perf_counter()-started,
                          'detections':[{'class':model.names[int(b.cls[0])],'confidence':float(b.conf[0]),'bbox':b.xyxy[0].tolist()} for b in result.boxes]}
                    report['runs'].append(item)
                    print(json.dumps(item,ensure_ascii=False),flush=True)
            del model
        report['passed']=True
    finally:
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
