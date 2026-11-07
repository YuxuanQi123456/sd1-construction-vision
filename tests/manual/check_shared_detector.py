"""Synthetic scheduling control for evidence isolation, never model accuracy."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'sitewatch/app'))
from cv_pipeline.detection import Detector, Detection


class SchedulingDetector(Detector):
    def __init__(self):
        self._frame_lock = threading.RLock()
        self.model_id = 'synthetic-ppe'
        self.custom = object()
        self.person = object()
        self.person_spec = {'id': 'synthetic-person'}
        self.last_branch_detections = {}
        self.last_inference_ms = 0

    def _run(self, model, frame, source, **kwargs):
        marker = int(frame[0, 0, 0])
        time.sleep(.002)
        self.last_inference_ms = marker
        return [Detection('Person', .5, (marker, marker, marker+10, marker+10), source, 'worker')]


def image(marker):
    return np.full((1, 1, 1), marker, dtype=np.uint16)


detector = SchedulingDetector()
barrier = threading.Barrier(2)


def legacy(marker):
    values = detector.detect(image(marker))
    barrier.wait(timeout=2)
    return values[0].bbox[0] == next(iter(detector.last_branch_detections.values()))[0].bbox[0]


with ThreadPoolExecutor(max_workers=2) as executor:
    legacy_results = list(executor.map(legacy, [1, 2]))
assert not all(legacy_results), 'Old post-return shared-state race was not reproduced'

with ThreadPoolExecutor(max_workers=4) as executor:
    snapshots = list(executor.map(lambda marker: detector.detect_frame(image(marker)), range(1, 21)))
for marker, (values, branches, elapsed) in enumerate(snapshots, 1):
    assert values[0].bbox[0] == marker
    assert all(item.bbox[0] == marker for branch in branches.values() for item in branch)
    assert elapsed == 2*marker

report = {'passed': True, 'kind': 'synthetic concurrency control; no AI outputs',
          'legacy_cross_frame_race_reproduced': True, 'isolated_snapshots_checked': 20}
Path(__file__).with_name('shared-detector-control.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
