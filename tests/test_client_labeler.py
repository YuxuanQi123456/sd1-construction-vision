"""Annotation saves must retain person labels and reject stale or invalid edits."""
import hashlib
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('client_labeler_server', ROOT / 'scripts/client_labeler_server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AnnotationSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack = self.root / 'downloads/client-labeling-pack'
        (self.pack / 'images/train').mkdir(parents=True)
        (self.pack / 'labels/train').mkdir(parents=True)
        (self.pack / 'images/train/帧.jpg').write_bytes(b'fixture')
        (self.pack / 'classes.txt').write_text('\n'.join(f'{i} class{i}' for i in range(25)))
        self.target = self.pack / 'labels/train/帧.txt'
        self.original = b'8 0.500000 0.500000 0.100000 0.200000\n'
        self.target.write_bytes(self.original)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), module.ClientLabelerHandler)
        self.server.project_root = self.root
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port) + '/api/labels/%E5%B8%A7.txt'

    def read(self):
        with urlopen(self.url) as response:
            return json.load(response)

    def save(self, text, version, **extra):
        body = json.dumps({'text': text, 'version': version, **extra}).encode()
        request = Request(self.url, body, {'Content-Type': 'application/json'}, method='PUT')
        with urlopen(request) as response:
            return json.load(response)

    def test_add_equipment_preserves_hidden_person_and_creates_history(self):
        state = self.read()
        result = self.save(state['text'] + '2 0.5 0.41 0.05 0.03\n', state['version'])
        self.assertEqual(result['rows'], 2)
        self.assertTrue(self.target.read_bytes().startswith(self.original))
        history = list((self.pack / 'label-history/帧.txt').glob('*.txt'))
        self.assertEqual([p.read_bytes() for p in history], [self.original])

    def test_stale_page_cannot_overwrite_new_equipment(self):
        old = self.read()
        self.save(old['text'] + '11 0.5 0.5 0.1 0.1\n', old['version'])
        before = self.target.read_bytes()
        with self.assertRaises(HTTPError) as exc:
            self.save('', old['version'])
        self.assertEqual(exc.exception.code, 409)
        self.assertEqual(self.target.read_bytes(), before)

    def test_invalid_and_nonfinite_coordinates_leave_original_bytes(self):
        for text in ['2 nan 0.5 0.1 0.1', '2 0.5 0.5 0 0.1', '25 0.5 0.5 0.1 0.1']:
            with self.subTest(text=text), self.assertRaises(HTTPError) as exc:
                self.save(text, hashlib.sha256(self.original).hexdigest())
            self.assertEqual(exc.exception.code, 400)
            self.assertEqual(self.target.read_bytes(), self.original)

    def test_completion_is_separate_from_labels_and_invalidated_by_edit(self):
        state = self.read()
        self.save(state['text'], state['version'], reviewed_classes=[2, 5, 7, 11])
        self.assertEqual(self.read()['reviewed_classes'], [2, 5, 7, 11])
        self.assertEqual(self.target.read_bytes(), self.original)
        self.save(state['text'] + '2 0.5 0.4 0.02 0.02', state['version'])
        self.assertEqual(self.read()['reviewed_classes'], [])


if __name__ == '__main__':
    unittest.main()
