"""Deterministic malformed-coordinate and process-ownership controls; no AI answers."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent / 'app'))
from region_review import cancel_job, crop_box, owns_review_listener, parse_option


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
    with tempfile.TemporaryDirectory() as temporary:
        process = Path(temporary) / '123'
        (process / 'fd').mkdir(parents=True)
        (process / 'net').mkdir()
        (process / 'fd/7').symlink_to('socket:[456]')
        table = process / 'net/tcp'
        row = '0: 0100007F:223E 00000000:0000 0A 00000000:00000000 00:00000000 00000000 1000 0 456'
        table.write_text('header\n' + row + '\n')
        argv = [b'python', b'--server-port', b'8766', b'--server-name', b'127.0.0.1']
        assert owns_review_listener(123, argv, Path(temporary))
        checks.append({'case': 'owned_exact_loopback_listener', 'passed': True})
        table.write_text('header\n' + row.replace('0 456', '0 999') + '\n')
        assert not owns_review_listener(123, argv, Path(temporary))
        checks.append({'case': 'other_process_owns_port_rejected', 'passed': True})
        table.write_text('header\n' + row.replace('0100007F', '00000000') + '\n')
        assert not owns_review_listener(123, argv, Path(temporary))
        checks.append({'case': 'wildcard_address_rejected', 'passed': True})
        table.write_text('header\n' + row + '\n')
        assert not owns_review_listener(123, [b'--server-port', b'8767'], Path(temporary))
        checks.append({'case': 'wrong_argv_rejected', 'passed': True})
    for raw, expected in [('A', 'A'), ('A＝明确佩戴工业安全帽', 'A'),
                           ('B＝头发或头皮清楚可见，未见工业安全帽', 'B'),
                           ('B<br>---<br>本次为图片或文本分析；结论待人工复核。', 'B'),
                           ('A---B', None), ('A<br>---<br>B', None),
                           ('A---B<br>---<br>本次为图片或文本分析；结论待人工复核。', None),
                           ('A不是答案', None),
                           ('B或者A', None), ('A=明确佩戴工业安全帽但不确定', None)]:
        assert parse_option(raw) == expected
    assert os.environ['GRADIO_ANALYTICS_ENABLED'] == 'False'
    assert os.environ['HF_HUB_DISABLE_TELEMETRY'] == '1'
    checks.append({'case': 'strict_parser_and_telemetry_env', 'passed': True})
    release, finished = threading.Event(), threading.Event()
    class StalledCancellation:
        def cancel(self):
            release.wait(2)
            finished.set()
    client = SimpleNamespace(httpx_kwargs={'timeout': 90})
    started = time.monotonic()
    cancel_job(client, StalledCancellation())
    elapsed = time.monotonic() - started
    assert elapsed < .5 and client.httpx_kwargs['timeout'] == 2
    release.set()
    assert finished.wait(1)
    checks.append({'case': 'stalled_cancellation_does_not_delay_failure',
                   'passed': True, 'return_seconds': elapsed, 'synthetic_control': True})
    record = {'at': datetime.now(timezone.utc).isoformat(), 'passed': True,
              'kind': 'synthetic boundary controls, no model outputs', 'checks': checks}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
