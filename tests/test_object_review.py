"""Original crop pixels, independent human review, and real frame navigation."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sitewatch/app'))
from object_review import crop_target, load_object_reviews, save_object_decision
from object_review_ui import evidence_index
from review_evidence import evidence_zip


class ObjectReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pixels = np.arange(80 * 120 * 3, dtype=np.uint8).reshape(80, 120, 3)
        cv2.imwrite(str(self.root / 'original.png'), self.pixels)
        cv2.imwrite(str(self.root / 'input.png'), cv2.resize(self.pixels, (60, 40)))
        self.result = {'status': 'complete', 'media_type': 'image', 'source_file': 'original.png',
                       'source_sha256': hashlib.sha256((self.root / 'original.png').read_bytes()).hexdigest(),
                       'frames': [{'frame_index': 0, 'timestamp_seconds': 0., 'input_file': 'input.png',
                                   'detection_dimensions_wh': [60, 40], 'detections': [
                                       {'class_name': 'person', 'confidence': .8, 'bbox': [10, 5, 30, 35], 'bbox_xyxy': [10, 5, 30, 35]}]}]}
        self.original = json.dumps(self.result).encode()
        (self.root / 'detections.json').write_bytes(self.original)

    def test_crop_maps_resized_detection_back_to_original_pixels(self):
        raw, evidence = crop_target(self.root, 0, 0)
        decoded = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(decoded, self.pixels[10:70, 20:60])
        self.assertEqual(evidence['crop_dimensions_wh'], [40, 60])
        self.assertEqual(evidence['detector_confidence'], .8)
        self.assertEqual((self.root / 'detections.json').read_bytes(), self.original)

    def test_manual_region_not_inserted_as_detector_result(self):
        _, evidence = crop_target(self.root, 0, manual_box=[1, 2, 9, 12])
        self.assertEqual(evidence['origin'], 'manual_region')
        self.assertIsNone(evidence['detector_label'])
        self.assertIsNone(evidence['detector_confidence'])
        save_object_decision(self.root, evidence, target_state='uncertain', helmet_state='pending', vest_state='uncertain')
        self.assertEqual((self.root / 'detections.json').read_bytes(), self.original)

    def test_saved_opinions_and_history_do_not_mutate_detection(self):
        raw, evidence = crop_target(self.root, 0, 0, part='head')
        saved = save_object_decision(self.root, evidence, target_state='confirmed', helmet_state='visible', vest_state='uncertain', note='人工测试')
        self.assertEqual((self.root / saved['crop_file']).read_bytes(), raw)
        save_object_decision(self.root, evidence, target_state='uncertain', helmet_state='uncertain', vest_state='pending')
        data = load_object_reviews(self.root)
        self.assertEqual(len(data['history']), 2)
        self.assertEqual(data['decisions'][evidence['target_id']]['judgement_source'], 'human')
        self.assertEqual((self.root / 'detections.json').read_bytes(), self.original)

    def test_invalid_or_changed_source_evidence_refuses_save(self):
        _, evidence = crop_target(self.root, 0, 0)
        (self.root / 'original.png').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            save_object_decision(self.root, evidence, target_state='confirmed', helmet_state='visible', vest_state='visible')
        self.assertFalse((self.root / 'object-reviews/decisions.json').exists())

    def test_keyframe_index_rejects_out_of_range_and_foreign_references(self):
        valid = {'frame_position': 0, 'frame_index': 0, 'input_file': 'input.png'}
        invalid = [{**valid, 'input_file': 'another-review.png'}, {**valid, 'frame_position': 50}]
        (self.root / 'events.json').write_text(json.dumps({'source_detections_sha256': hashlib.sha256(self.original).hexdigest(), 'events': [{'type': 'zone_enter', 'track_id': 'person-1', 'evidence': [valid, *invalid]}]}))
        entries = evidence_index(self.root, self.result)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['frame_position'], 0)

    def test_unchanged_evidence_reuses_zip_and_new_manual_record_invalidates_it(self):
        import zipfile
        archive = evidence_zip(self.root)
        before = archive.stat().st_mtime_ns
        self.assertEqual(evidence_zip(self.root).stat().st_mtime_ns, before)
        _, evidence = crop_target(self.root, 0, 0)
        save_object_decision(self.root, evidence, target_state='confirmed', helmet_state='pending', vest_state='pending')
        with zipfile.ZipFile(evidence_zip(self.root)) as package:
            self.assertIn('object-reviews/decisions.json', package.namelist())
            self.assertEqual(package.read('detections.json'), self.original)


if __name__ == '__main__':
    unittest.main()
