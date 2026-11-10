"""A short real encoded fixture verifies full-frame inference, evidence and failure."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sitewatch/app'))
from cv_pipeline.detection import Detection
from video_replay import build_video_replay, existing_replay


class FixtureDetector:
    conf_threshold = .25
    provenance = {'id': 'fixture', 'sha256': 'fixture-hash', 'inference_imgsz': 640, 'profile': 'standard'}

    def __init__(self, fail_at=None):
        self.calls = 0
        self.fail_at = fail_at

    def detect_frame(self, image):
        self.calls += 1
        if self.calls == self.fail_at:
            raise ValueError('intentional inference failure')
        return [Detection('person', .8, (10, 8, 30, 40), 'fixture', 'worker', 0, (10., 8., 30., 40.), 'person')], {}, .1


class VideoReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / 'original.mp4'
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'mp4v'), 5, (64, 48))
        for i in range(5):
            writer.write(np.full((48, 64, 3), 30 + i * 20, dtype=np.uint8))
        writer.release()
        self.source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        record = {'status': 'complete', 'media_type': 'video', 'source_file': 'original.mp4', 'source_sha256': self.source_sha,
                  'model': FixtureDetector.provenance, 'settings': {'confidence': .25, 'max_seconds': .8, 'preserve_resolution': True, 'image_enhancement': False},
                  'frames': []}
        self.original = json.dumps(record).encode()
        (self.root / 'detections.json').write_bytes(self.original)

    def test_every_frame_is_inferred_and_replay_is_browser_playable(self):
        detector = FixtureDetector()
        saved = build_video_replay(self.root, detector)
        self.assertEqual(detector.calls, 4)
        self.assertEqual(saved['decoded_frame_count'], 4)
        frames = [json.loads(x) for x in (self.root / saved['frames_file']).read_text().splitlines()]
        self.assertEqual([x['frame_index'] for x in frames], list(range(4)))
        self.assertTrue(all(x['detections'][0]['confidence'] == .8 for x in frames))
        self.assertEqual(existing_replay(self.root), saved)
        build_video_replay(self.root, detector)
        self.assertEqual(detector.calls, 4)  # Replaying is zero new inference.
        self.assertEqual((self.root / 'detections.json').read_bytes(), self.original)
        self.assertEqual(hashlib.sha256((self.root / 'original.mp4').read_bytes()).hexdigest(), self.source_sha)

    def test_failed_inference_does_not_publish_partial_mp4_or_success(self):
        with self.assertRaises(ValueError):
            build_video_replay(self.root, FixtureDetector(fail_at=2))
        self.assertIsNone(existing_replay(self.root))
        self.assertFalse((self.root / 'video-replay').exists())
        self.assertEqual((self.root / 'detections.json').read_bytes(), self.original)

    def test_cached_replay_refuses_changed_original_video(self):
        build_video_replay(self.root, FixtureDetector())
        (self.root / 'original.mp4').write_bytes(b'changed original')
        self.assertIsNone(existing_replay(self.root))


if __name__ == '__main__':
    unittest.main()
