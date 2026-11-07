"""Pinned native PPE inference and the upstream optional person companion on CPU."""
from __future__ import annotations

import logging
import hashlib
import json
import os
import sys
import time
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

MODEL_SHA256 = "c2db52b9be8ccd5bcc09d6e0f9498a6e442e47eb6f6b62850db11530b77651ab"
MODEL_NAMES = ["Excavator", "Gloves", "Hardhat", "Ladder", "Mask", "NO-Hardhat", "NO-Mask", "NO-Safety Vest", "Person", "SUV", "Safety Cone", "Safety Vest", "bus", "dump truck", "fire hydrant", "machinery", "mini-van", "sedan", "semi", "trailer", "truck and trailer", "truck", "van", "vehicle", "wheel loader"]

# Categories used downstream by fusion / drawing.
CATEGORIES = {
    "ppe_violation": {"NO-Hardhat", "NO-Safety Vest", "NO-Mask"},
    "ppe_compliant": {"Hardhat", "Safety Vest", "Mask"},
    "worker": {"Person", "person"},
    "hazard": {"machinery", "vehicle", "truck", "bus", "car"},
    "marker": {"Safety Cone"},
}


def _category_for(name: str) -> str:
    if name in {'no-hardhat', 'no-safety vest', 'no-mask', 'no-goggles', 'no-gloves'}:
        return 'ppe_violation'
    if name in {'hardhat', 'safety vest', 'gloves', 'goggles', 'safety shoes'}:
        return 'ppe_compliant'
    if name == 'person':
        return 'worker'
    for cat, members in CATEGORIES.items():
        if name in members:
            return cat
    return "other"


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    source: str  # Pinned branch identifier, retained in exported evidence.
    category: str  # ppe_violation | ppe_compliant | worker | hazard | marker | other
    class_id: int = -1
    bbox_xyxy: tuple[float, float, float, float] | None = None
    canonical_class: str | None = None


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class Detector:
    """Runs the original custom model; missing/invalid weights are fatal.

    Category names are retained for the upstream drawing API. They are model
    labels, not a determination of regulatory compliance.
    """

    def __init__(
        self,
        custom_path: str | None = None,
        conf_threshold: float = 0.4,
        model_id: str = 'sitewatch',
        profile: str = 'standard',
    ) -> None:
        # Import lazily so the module imports cleanly even before the
        # ultralytics package is installed (useful for unit-test discovery).
        from ultralytics import YOLO
        import torch

        torch.set_num_threads(max(1, int(os.environ.get("SITEWATCH_CPU_THREADS", "2"))))
        self.conf_threshold = float(conf_threshold)
        if profile not in {'standard', 'distant'}:
            raise ValueError('Unknown detection profile')
        self.profile = profile
        self.inference_imgsz = 1280 if profile == 'distant' else 640
        if model_id not in {'sitewatch', 'constructelligence-v03'}:
            raise ValueError('Only the baseline and explicitly registered comparison model are available')
        specs = json.loads((Path(__file__).resolve().parents[2] / 'model-candidates.json').read_text())['models']
        spec = next(item for item in specs if item['id'] == model_id)
        project = Path(os.environ.get('SITEWATCH_PROJECT_ROOT', Path(__file__).resolve().parents[3]))
        default_path = os.environ.get('SITEWATCH_MODEL_PATH') if model_id == 'sitewatch' else None
        self.model_id = model_id
        self.model_path = Path(custom_path or default_path or project / spec['weights']).resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Required SiteWatch PPE model missing: {self.model_path}. COCO fallback is disabled.")
        self.model_sha256 = hashlib.sha256(self.model_path.read_bytes()).hexdigest()
        if self.model_sha256 != spec['sha256']:
            raise ValueError(f"SiteWatch model SHA256 mismatch: {self.model_sha256}")
        self.custom = YOLO(str(self.model_path))
        self.names = dict(self.custom.names)
        if [self.names[i] for i in range(len(self.names))] != spec['expected_names']:
            raise ValueError(f"Unexpected SiteWatch class names: {self.names}")
        self.canonical_classes = {value: key for key, value in spec['classes'].items()}
        self.provenance = {'id': model_id, 'repository': spec['source'], 'commit': spec['revision'],
                           'sha256': self.model_sha256, 'names': self.names,
                           'weight_license': spec['license'], 'device': 'cpu',
                           'profile': profile, 'inference_imgsz': self.inference_imgsz}
        self.person = None
        self.person_spec = None
        if profile == 'distant':
            companion = json.loads((Path(__file__).resolve().parents[2] / 'person-model.json').read_text())
            person_path = project / companion['weights']
            if (not person_path.is_file() or person_path.stat().st_size != companion['bytes']
                    or hashlib.sha256(person_path.read_bytes()).hexdigest() != companion['sha256']):
                raise ValueError('Pinned companion person weight missing or invalid; standard mode remains available')
            self.person = YOLO(str(person_path))
            if len(self.person.names) != 80 or self.person.names.get(0) != 'person':
                raise ValueError('Unexpected COCO companion vocabulary')
            self.person_spec = companion
            self.provenance['person_companion'] = {**companion, 'actual_names': dict(self.person.names),
                                                   'device': 'cpu', 'purpose': 'person only; no PPE labels'}
        self.last_inference_ms = 0.0
        self.last_branch_detections = {}
        self._frame_lock = threading.RLock()

    def _run(self, model, frame: np.ndarray, source: str, *, person_only=False) -> list[Detection]:
        start = time.perf_counter()
        kwargs = {'classes': [0]} if person_only else {}
        results = model.predict(frame, conf=self.conf_threshold, verbose=False, device="cpu",
                                imgsz=640 if person_only else self.inference_imgsz, **kwargs)
        self.last_inference_ms = (time.perf_counter() - start) * 1000
        out: list[Detection] = []
        if not results:
            return out
        r = results[0]
        names = r.names
        if r.boxes is None:
            return out
        for box in r.boxes:
            cls = int(box.cls[0])
            conf = float(box.conf[0])
            xyxy = box.xyxy[0].tolist()
            x1, y1, x2, y2 = (int(round(v)) for v in xyxy)
            class_name = names.get(cls, str(cls)) if isinstance(names, dict) else names[cls]
            out.append(
                Detection(
                    class_name=class_name,
                    confidence=conf,
                    bbox=(x1, y1, x2, y2),
                    source=source,
                    category=_category_for(class_name),
                    class_id=cls,
                    bbox_xyxy=tuple(float(v) for v in xyxy),
                    canonical_class='person' if person_only else self.canonical_classes.get(cls),
                )
            )
        return out

    def _detect(self, frame: np.ndarray) -> list[Detection]:
        if frame is None or frame.size == 0:
            self.last_branch_detections = {}
            self.last_inference_ms = 0.0
            return []
        custom = self._run(self.custom, frame, self.model_id)
        custom_ms = self.last_inference_ms
        self.last_branch_detections = {self.model_id: custom}
        if self.person is None:
            return custom
        people = self._run(self.person, frame, self.person_spec['id'], person_only=True)
        self.last_inference_ms += custom_ms
        self.last_branch_detections[self.person_spec['id']] = people
        # Reuse upstream overlap deduplication, restricted to whole-person boxes.
        # A small helmet box must never suppress a whole worker detection.
        return custom + [p for p in people if not any(
            cd.category == 'worker' and _iou(p.bbox, cd.bbox) > .5 for cd in custom)]

    def detect(self, frame: np.ndarray) -> list[Detection]:
        with self._frame_lock:
            return self._detect(frame)

    def detect_frame(self, frame: np.ndarray):
        """Return this call's evidence snapshot before another session can infer."""
        with self._frame_lock:
            detections = self._detect(frame)
            branches = {source: list(values) for source, values in self.last_branch_detections.items()}
            return detections, branches, self.last_inference_ms


def _cli(path: str) -> None:
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    det = Detector()
    print(f"loaded image {img.shape}")
    out = det.detect(img)
    for d in out:
        print(f"  {d.source:>9}  {d.class_name:<18} {d.confidence:.2f}  {d.bbox}  [{d.category}]")
    print(f"total: {len(out)} detections")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m cv_pipeline.detection <image_path>", file=sys.stderr)
        sys.exit(1)
    _cli(sys.argv[1])
