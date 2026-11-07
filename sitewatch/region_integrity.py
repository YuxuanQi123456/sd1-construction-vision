"""Check real detector→region→GPT API→evidence ZIP without mocked answers."""
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile


def check_real_region(image_path, project_root, destination):
    import cv2
    import numpy as np
    from cv_pipeline.detection import Detector
    from review_evidence import review_file, evidence_zip
    from region_review import head_indices, review_head_region
    from review_api import ReviewAPIError
    root, destination = Path(project_root), Path(destination)
    if destination.exists():
        raise ValueError('Choose a new artifact directory')
    result = review_file(image_path, Detector(), destination)
    before = (destination / 'detections.json').read_bytes()
    frame = result['frames'][0]
    indices = head_indices(frame)
    assert indices, 'This real control must have a head detection'
    index = indices[0]
    controls = []
    try:
        review_head_region(destination, -1, index, root)
    except ValueError as exc:
        controls.append({'case': 'invalid_frame', 'passed': True, 'error': str(exc)})
    else:
        raise AssertionError('Negative frame index was accepted')
    non_heads = [i for i in range(len(frame['detections'])) if i not in indices]
    assert non_heads
    try:
        review_head_region(destination, 0, non_heads[0], root)
    except ValueError as exc:
        controls.append({'case': 'not_a_head_class', 'passed': True, 'error': str(exc)})
    else:
        raise AssertionError('A non-head box was treated as a head')
    # An isolated project without a Key must fail before any paid request.
    with tempfile.TemporaryDirectory(dir=root / '.runtime', prefix='head-identity-control-') as temporary:
        try:
            review_head_region(destination, 0, index, temporary)
        except ReviewAPIError as exc:
            failed = sorted(destination.rglob('review.json'))
            assert len(failed) == 1
            assert json.loads(failed[0].read_text())['status'] == 'failed'
            failed_bytes = failed[0].read_bytes()
            controls.append({'case': 'missing_project_api_key', 'passed': True, 'error': str(exc)})
        else:
            raise AssertionError('A project without an API key produced a result')
    record = review_head_region(destination, 0, index, root)
    assert record['status'] == 'complete'
    assert failed[0].read_bytes() == failed_bytes, 'Retry overwrote the failed attempt'
    assert (destination / 'detections.json').read_bytes() == before, 'Detector output was rewritten'
    assert record['opinion']['classification_confidence'] is None
    original = cv2.imread(str(destination / record['input_file']))
    crop = cv2.imread(str(destination / record['crop_file']))
    x1, y1, x2, y2 = record['crop_box_in_input']
    assert np.array_equal(crop, original[y1:y2, x1:x2]), 'Crop pixels differ from recorded source region'
    assert record['detector_detection'] == json.loads(json.dumps(frame['detections'][index])), 'Serialized detector values changed'
    package = evidence_zip(destination)
    with zipfile.ZipFile(package) as archive:
        assert hashlib.sha256(archive.read(record['crop_file'])).hexdigest() == record['crop_sha256']
        assert archive.read('detections.json') == before
        assert any(name.endswith('/latest.json') for name in archive.namelist())
        assert any(name.endswith('/review.json') for name in archive.namelist())
    return {'artifact_dir': str(destination), 'controls': controls, 'record': record,
            'detector_bytes_unchanged': True, 'crop_pixels_equal_to_saved_input_region': True,
            'failed_attempt_retained': True, 'zip_crop_sha_verified': True,
            'zip_original_detector_json_equal': True}
