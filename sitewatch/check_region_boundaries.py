"""Deterministic malformed-coordinate and strict-answer controls; no AI requests."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'app'))
from region_review import crop_box, parse_option


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a fresh evidence file')
    checks = []
    for name, bbox in [('left', [-100, 10, -50, 30]), ('right', [200, 10, 250, 30]),
                       ('above', [10, -100, 30, -50]), ('below', [10, 200, 30, 250]),
                       ('padding_must_not_rescue_offscreen', [-100, 10, -1, 30]),
                       ('empty', [10, 10, 10, 20]), ('nan', [0, 0, float('nan'), 20])]:
        try:
            crop_box(bbox, 100, 100)
        except ValueError as exc:
            checks.append({'case': name, 'rejected': True, 'error': str(exc)})
        else:
            raise AssertionError(f'{name} accepted')
    assert crop_box([-5, -5, 105, 105], 100, 100) == [0, 0, 100, 100]
    checks.append({'case': 'partially_outside_clipped', 'passed': True})
    for raw, expected in [('A', 'A'), ('A＝明确佩戴工业安全帽', 'A'),
                           ('B＝头发或头皮清楚可见，未见工业安全帽', 'B'),
                           ('B<br>---<br>本次为图片或文本分析；结论待人工复核。', None),
                           ('A---B', None), ('A<br>---<br>B', None),
                           ('A---B<br>---<br>本次为图片或文本分析；结论待人工复核。', None),
                           ('A不是答案', None),
                           ('B或者A', None), ('A=明确佩戴工业安全帽但不确定', None)]:
        assert parse_option(raw) == expected
    checks.append({'case': 'strict_answer_parser', 'passed': True})
    record = {'at': datetime.now(timezone.utc).isoformat(), 'passed': True,
              'kind': 'synthetic boundary controls, no model outputs', 'checks': checks}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
