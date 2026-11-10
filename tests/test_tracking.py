import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sitewatch/app"))

import tracking  # noqa: E402
import safety_summary  # noqa: E402


def _frame(index, timestamp, detections):
    return {
        "frame_index": index,
        "timestamp_seconds": timestamp,
        "input_file": f"frame-{index:06d}-input.jpg",
        "detection_dimensions_wh": [100, 100],
        "detections": detections,
    }


class TrackingEvidenceTests(unittest.TestCase):
    def test_another_review_does_not_reset_live_tracker_object_ids(self):
        def people(count):
            return [{'class_name': 'person', 'confidence': .9, 'bbox_xyxy': [20 + i * 120, 20, 60 + i * 120, 120],
                     'category': 'worker', 'class_id': 0} for i in range(count)]
        first = tracking.ByteTrackEvidence()
        original = first.update(people(3), [600, 400])
        first.update(people(3), [600, 400])
        tracking.ByteTrackEvidence()  # Simulates another review/replay starting.
        first.update(people(4), [600, 400])
        current = first.update(people(4), [600, 400])
        self.assertEqual(len(current), 4)
        self.assertTrue({x['track_id'] for x in original}.issubset({x['track_id'] for x in current}))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sd1-tracking-")
        self.review = Path(self.temp.name)
        self.image = np.zeros((100, 100, 3), dtype=np.uint8)
        self.detections = [
            {"class_name": "Person", "confidence": 0.9, "bbox": [10, 10, 30, 50],
             "bbox_xyxy": [10, 10, 30, 50], "category": "worker", "class_id": 8},
            {"class_name": "Excavator", "confidence": 0.8, "bbox": [60, 20, 90, 70],
             "bbox_xyxy": [60, 20, 90, 70], "category": "hazard", "class_id": 0},
        ]
        self.frames = []
        for index in range(3):
            filename = self.review / f"frame-{index:06d}-input.jpg"
            self.assertTrue(cv2.imwrite(str(filename), self.image))
            moved = json.loads(json.dumps(self.detections))
            moved[0]["bbox"] = moved[0]["bbox_xyxy"] = [10 + index, 10, 30 + index, 50]
            moved[1]["bbox"] = moved[1]["bbox_xyxy"] = [60 + index, 20, 90 + index, 70]
            self.frames.append(_frame(index, float(index), moved))
        self.result = {"status": "complete", "media_type": "video", "frames": self.frames}
        (self.review / "detections.json").write_text(json.dumps(self.result, indent=2) + "\n")
        self.detections_sha = hashlib.sha256((self.review / "detections.json").read_bytes()).hexdigest()
        self.addCleanup(self.temp.cleanup)

    def test_open_source_bytetrack_creates_ids_without_mutating_detector_json(self):
        summary = tracking.augment_tracking(self.review, self.result, sample_seconds=1.0)
        self.assertEqual(summary["backend"]["algorithm"], "ByteTrack")
        self.assertGreaterEqual(summary["track_count"], 2)
        record = json.loads((self.review / "tracks.json").read_text())
        self.assertEqual(record["source_detections_sha256"], self.detections_sha)
        self.assertEqual(len(record["frames"]), 3)
        self.assertTrue(all((self.review / item["track_overlay_file"]).is_file()
                            for item in record["frames"]))
        self.assertEqual(hashlib.sha256((self.review / "detections.json").read_bytes()).hexdigest(), self.detections_sha)

    def test_candidate_zone_derives_pending_enter_and_stay_events(self):
        tracking.augment_tracking(self.review, self.result, sample_seconds=1.0)
        saved = tracking.save_zone_events(self.review, [[0, 0], [99, 0], [99, 99], [0, 99]], stay_seconds=1.0)
        self.assertGreaterEqual(len(saved["events"]), 2)
        self.assertTrue(all(item["status"] == "pending" for item in saved["events"]))
        self.assertTrue(all(item["evidence"] for item in saved["events"]))
        zones = json.loads((self.review / "zones.json").read_text())
        events = json.loads((self.review / "events.json").read_text())
        self.assertEqual(zones["zones"][0]["coordinate_basis"], "detection_frame_pixels")
        self.assertEqual(len(events["events"]), len(saved["events"]))

    def test_summary_prefers_event_keyframes_when_events_exist(self):
        (self.review / "events.json").write_text(json.dumps({"events": [{
            "type": "zone_stay", "track_id": "person-1",
            "evidence": [{"frame_position": 1}, {"frame_position": 2}],
            "start_seconds": 1.0, "end_seconds": 2.0,
        }]}, ensure_ascii=False))
        positions, context = safety_summary._event_context(self.review, len(self.frames))
        self.assertEqual(positions, [1, 2])
        self.assertEqual(context[0]["track_id"], "person-1")


if __name__ == "__main__":
    unittest.main()
