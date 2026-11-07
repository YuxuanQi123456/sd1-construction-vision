"""Exercise the real local HTTP transport without a billable service or real Key."""
import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import BadStatusLine, IncompleteRead, LineTooLong
import importlib
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "sitewatch/app"
sys.path.insert(0, str(APP))
import review_api as api
import region_review as region

# A complete 1x1 PNG. Requests must preserve these exact bytes.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j8d8AAAAASUVORK5CYII=")
DUMMY_KEY = "test-only-never-a-real-api-key"


def response(text="A", **updates):
    data = {"id": "resp_fixture", "status": "completed", "model": "gpt-6.1-sol",
            "output": [{"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15,
                      "output_tokens_details": {"reasoning_tokens": 2}}}
    data.update(updates)
    return data


@contextmanager
def fixture_server(reply=None, status=200, headers=None, delay=0, on_request=None):
    requests = []
    raw = reply if isinstance(reply, bytes) else json.dumps(response() if reply is None else reply).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
            if on_request:
                on_request(requests[-1])
            if delay:
                time.sleep(delay)
            try:
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


class ReviewAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sd1-review-api-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.crop = self.root / "crop.png"
        self.crop.write_bytes(PNG)

    def config(self, **values):
        data = {**api.DEFAULT_CONFIG, "api_key": DUMMY_KEY, **values}
        file = self.root / api.LOCAL_CONFIG
        file.parent.mkdir(exist_ok=True)
        file.write_text(json.dumps(data))
        return file

    def test_default_model_max_and_no_environment_key_adoption(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": DUMMY_KEY, "SD1_REVIEW_API_KEY": DUMMY_KEY}):
            cfg = api.load_review_config(self.root)
            self.assertEqual(cfg["api_key"], "")
            self.assertEqual(cfg["model"], "gpt-6.1-sol")
            self.assertEqual(cfg["reasoning_effort"], "max")

    def test_missing_key_status_and_classification_never_touch_network_or_gradio(self):
        with patch.object(api, "build_opener", side_effect=AssertionError("network")), patch.dict(sys.modules, {"gradio_client": None}):
            status = region.backend_status(self.root)
            self.assertFalse(status["ready"])
            self.assertFalse(status["connectivity_verified"])
            self.assertEqual(status["provider"], "openai")
            self.assertEqual(status["model"], "gpt-6.1-sol")
            with self.assertRaisesRegex(api.ReviewAPIError, "Key"):
                region.classify_crop(self.crop, self.root)

    def test_configured_status_is_not_a_connectivity_claim_and_hides_key(self):
        self.config()
        with patch.object(api, "build_opener", side_effect=AssertionError("network")):
            status = api.api_backend_status(self.root)
        self.assertTrue(status["ready"])
        self.assertFalse(status["connectivity_verified"])
        self.assertNotIn(DUMMY_KEY, json.dumps(status))
        self.assertNotIn("api_key", status)

    def test_exact_crop_model_max_store_false_and_original_prompt_over_http(self):
        with fixture_server() as (url, requests):
            self.config(base_url=url)
            opinion = region.classify_crop(self.crop, self.root)
        self.assertEqual(len(requests), 1)
        request = requests[0]
        payload = json.loads(request["body"])
        self.assertEqual(request["path"], "/v1/responses")
        self.assertEqual(request["headers"]["Authorization"], "Bearer " + DUMMY_KEY)
        self.assertEqual(payload["model"], "gpt-6.1-sol")
        self.assertEqual(payload["reasoning"], {"effort": "max"})
        self.assertIs(payload["store"], False)
        self.assertEqual(payload["max_output_tokens"], 4096)
        self.assertEqual(set(payload), {"model", "reasoning", "store", "max_output_tokens", "input"})
        content = payload["input"][0]["content"]
        self.assertEqual(content[0], {"type": "input_text", "text": region.PROMPT})
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(base64.b64decode(content[1]["image_url"].split(",", 1)[1]), PNG)
        self.assertEqual(opinion["option"], "A")
        self.assertIsNone(opinion["classification_confidence"])
        self.assertEqual(opinion["backend"]["provider"], "openai")
        self.assertTrue(opinion["backend"]["connectivity_verified"])
        self.assertNotIn(DUMMY_KEY, json.dumps(opinion))

    def test_jpeg_mime_comes_from_original_bytes(self):
        data = b"\xff\xd8\xfffixture-jpeg"
        self.crop.write_bytes(data)
        with fixture_server() as (url, requests):
            self.config(base_url=url)
            api.request_image_opinion(self.crop, self.root, region.PROMPT)
        uri = json.loads(requests[0]["body"])["input"][0]["content"][1]["image_url"]
        self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
        self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), data)

    def test_strict_answer_parsing_does_not_invent_a_classification(self):
        with fixture_server(response("A，也可能是普通帽")) as (url, requests):
            self.config(base_url=url)
            opinion = region.classify_crop(self.crop, self.root)
        self.assertIsNone(opinion["option"])
        self.assertIsNone(opinion["classification_confidence"])
        self.assertEqual(opinion["raw_answer"], "A，也可能是普通帽")

    def test_http_error_body_and_url_error_do_not_leak_credentials_or_retry(self):
        with fixture_server({"error": {"message": "Authorization: Bearer " + DUMMY_KEY}}, status=401) as (url, requests):
            self.config(base_url=url)
            with self.assertRaises(api.ReviewAPIError) as caught:
                api.request_image_opinion(self.crop, self.root, region.PROMPT)
        self.assertEqual(len(requests), 1)
        self.assertIn("401", str(caught.exception))
        self.assertNotIn(DUMMY_KEY, str(caught.exception))

    def test_api_reflection_is_redacted_and_only_white_list_metadata_is_saved(self):
        data = response("A " + DUMMY_KEY, id="resp_" + DUMMY_KEY, model="model-" + DUMMY_KEY)
        data["request"] = {"api_key": DUMMY_KEY}
        data["usage"]["secret"] = DUMMY_KEY
        data["usage"]["output_tokens_details"]["api_key"] = DUMMY_KEY
        with fixture_server(data) as (url, requests):
            self.config(base_url=url)
            opinion = region.classify_crop(self.crop, self.root)
        self.assertNotIn(DUMMY_KEY, json.dumps(opinion))
        self.assertNotIn("request", opinion)
        self.assertEqual(opinion["usage"], {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15, "output_tokens_details": {"reasoning_tokens": 2}})
        self.assertIsNone(opinion["option"])

    def test_metadata_is_redacted_before_length_limit(self):
        value = "x" * 250 + DUMMY_KEY
        with fixture_server(response(id=value, model=value)) as (url, requests):
            self.config(base_url=url)
            opinion = region.classify_crop(self.crop, self.root)
        self.assertNotIn(DUMMY_KEY[:6], opinion["response_id"])
        self.assertNotIn(DUMMY_KEY[:6], opinion["response_model"])
        self.assertLessEqual(len(opinion["response_id"]), 256)

    def test_http_protocol_errors_are_safe(self):
        self.config()
        for error in [BadStatusLine(DUMMY_KEY), IncompleteRead(DUMMY_KEY.encode()), LineTooLong(DUMMY_KEY)]:
            with self.subTest(error=type(error).__name__):
                opener = type("Opener", (), {"open": lambda *a, **k: (_ for _ in ()).throw(error)})()
                with patch.object(api, "build_opener", return_value=opener):
                    with self.assertRaises(api.ReviewAPIError) as caught:
                        api.request_image_opinion(self.crop, self.root, region.PROMPT)
                self.assertNotIn(DUMMY_KEY, str(caught.exception))

    def test_failed_attempt_record_redacts_network_error_and_preserves_detector(self):
        self.config()
        review = self.root / "review"
        review.mkdir()
        (review / "input.png").write_bytes(PNG)
        detection = {"class_name": "Hardhat", "bbox": [0, 0, 1, 1], "confidence": 0.8}
        original = {"status": "complete", "source_sha256": hashlib.sha256(PNG).hexdigest(),
                    "model": {"id": "fixture"}, "frames": [{"input_file": "input.png",
                    "frame_index": 0, "timestamp_seconds": 0, "detections": [detection]}]}
        before = json.dumps(original).encode()
        (review / "detections.json").write_bytes(before)

        class Image:
            shape = (1, 1, 3)
            size = 3
            def __getitem__(self, index):
                return self

        def save(path, image):
            Path(path).write_bytes(PNG)
            return True

        cv2 = type("CV2", (), {"imread": staticmethod(lambda p: Image()), "imwrite": staticmethod(save)})
        opener = type("Opener", (), {"open": lambda *a, **k: (_ for _ in ()).throw(BadStatusLine(DUMMY_KEY))})()
        with patch.dict(sys.modules, {"cv2": cv2}), patch.object(api, "build_opener", return_value=opener):
            with self.assertRaises(api.ReviewAPIError):
                region.review_head_region(review, 0, 0, self.root)
        self.assertEqual((review / "detections.json").read_bytes(), before)
        saved = list(review.rglob("review.json")) + list(review.rglob("latest.json"))
        self.assertEqual(len(saved), 2)
        for file in saved:
            self.assertNotIn(DUMMY_KEY, file.read_text())
            self.assertEqual(json.loads(file.read_text())["status"], "failed")

    def test_failed_http_attempt_keeps_the_exact_config_used_even_if_file_changes(self):
        review = self.root / "review-snapshot"
        review.mkdir()
        (review / "input.png").write_bytes(PNG)
        detection = {"class_name": "Hardhat", "bbox": [0, 0, 1, 1], "confidence": 0.8}
        original = {"status": "complete", "source_sha256": hashlib.sha256(PNG).hexdigest(),
                    "model": {"id": "fixture"}, "frames": [{"input_file": "input.png",
                    "frame_index": 0, "timestamp_seconds": 0, "detections": [detection]}]}
        before = json.dumps(original).encode()
        (review / "detections.json").write_bytes(before)

        class Image:
            shape = (1, 1, 3)
            size = 3
            def __getitem__(self, index):
                return self

        def save(path, image):
            Path(path).write_bytes(PNG)
            return True

        cv2 = type("CV2", (), {"imread": staticmethod(lambda p: Image()), "imwrite": staticmethod(save)})

        def change_config(request):
            self.config(model="changed-after-send", reasoning_effort="low")

        with fixture_server({"error": "denied"}, status=401, on_request=change_config) as (url, requests):
            self.config(base_url=url)
            original_snapshot = region.review_backend_snapshot

            def change_before_transport(config, project_root):
                safe = original_snapshot(config, project_root)
                self.config(base_url=url, model="changed-before-send", reasoning_effort="low")
                return safe

            with (patch.dict(sys.modules, {"cv2": cv2}),
                  patch.object(region, "review_backend_snapshot", side_effect=change_before_transport),
                  patch.object(api, "load_review_config", wraps=api.load_review_config) as reread):
                with self.assertRaises(api.ReviewAPIError):
                    region.review_head_region(review, 0, 0, self.root)
                self.assertEqual(reread.call_count, 0, "Transport must use the same validated configuration snapshot")
        payload = json.loads(requests[0]["body"])
        record = json.loads(next(review.rglob("review.json")).read_text())
        self.assertEqual(payload["model"], record["request_backend"]["model"])
        self.assertEqual(payload["reasoning"]["effort"], record["request_backend"]["reasoning_effort"])
        self.assertEqual(record["request_backend"]["model"], "gpt-6.1-sol")
        self.assertEqual(record["request_backend"]["reasoning_effort"], "max")
        self.assertEqual(record["prompt"], payload["input"][0]["content"][0]["text"])
        self.assertEqual(record["prompt_sha256"], hashlib.sha256(record["prompt"].encode()).hexdigest())
        self.assertIsNone(record["classification_confidence"])
        self.assertEqual(record["status"], "failed")
        self.assertNotIn(DUMMY_KEY, json.dumps(record))
        self.assertEqual((review / "detections.json").read_bytes(), before)

    def test_redirect_does_not_send_authorization_to_destination(self):
        with fixture_server() as (sink, received):
            with fixture_server(b"", status=302, headers={"Location": sink + "/responses"}) as (url, sent):
                self.config(base_url=url)
                with self.assertRaisesRegex(api.ReviewAPIError, "重定向"):
                    api.request_image_opinion(self.crop, self.root, region.PROMPT)
        self.assertEqual(len(sent), 1)
        self.assertEqual(received, [])

    def test_incomplete_refusal_missing_text_and_malformed_json_fail(self):
        refused = response()
        refused["output"][0]["content"] = [{"type": "refusal", "refusal": DUMMY_KEY}]
        choices = [response(status="incomplete"), refused, response(output=[]),
                   response(error={"message": DUMMY_KEY}), b"not-json"]
        for value in choices:
            with self.subTest(value=type(value).__name__):
                with fixture_server(value) as (url, requests):
                    self.config(base_url=url)
                    with self.assertRaises(api.ReviewAPIError) as caught:
                        region.classify_crop(self.crop, self.root)
                self.assertEqual(len(requests), 1)
                self.assertNotIn(DUMMY_KEY, str(caught.exception))

    def test_timeout_is_visible_and_not_retried(self):
        with fixture_server(delay=1.4) as (url, requests):
            self.config(base_url=url, timeout_seconds=1)
            with self.assertRaisesRegex(api.ReviewAPIError, "超时"):
                api.request_image_opinion(self.crop, self.root, region.PROMPT)
        self.assertEqual(len(requests), 1)

    def test_response_size_limit(self):
        with fixture_server(b" " * (api.MAX_RESPONSE_BYTES + 1)) as (url, requests):
            self.config(base_url=url)
            with self.assertRaisesRegex(api.ReviewAPIError, "响应过大"):
                api.request_image_opinion(self.crop, self.root, region.PROMPT)

    def test_invalid_or_oversized_crop_never_sends_request(self):
        self.config()
        for content, maximum in [(b"not an image", api.MAX_CROP_BYTES), (PNG, len(PNG) - 1)]:
            self.crop.write_bytes(content)
            with patch.object(api, "build_opener", side_effect=AssertionError("network")), patch.object(api, "MAX_CROP_BYTES", maximum):
                with self.assertRaises(api.ReviewAPIError):
                    api.request_image_opinion(self.crop, self.root, region.PROMPT)

    def test_config_validation_never_falls_back_or_echoes_values(self):
        cases = [dict(provider="wrong" + DUMMY_KEY), dict(provider=[]), dict(reasoning_effort=[]),
                 dict(base_url="http://example.com/v1"), dict(base_url="https://u:p@host/v1"),
                 dict(base_url="https://host/v1?key=" + DUMMY_KEY), dict(base_url="https://host/v1#fragment"),
                 dict(base_url="https://host/v1/responses"), dict(timeout_seconds=float("nan")), dict(timeout_seconds=10**999),
                 dict(max_output_tokens=True), dict(api_key="token\r\nHeader: value")]
        for values in cases:
            with self.subTest(fields=list(values)):
                self.config(**values)
                with patch.object(api, "build_opener", side_effect=AssertionError("network")):
                    status = region.backend_status(self.root)
                    self.assertFalse(status["ready"])
                    self.assertNotIn(DUMMY_KEY, json.dumps(status))
                    with self.assertRaises(api.ReviewAPIError):
                        region.classify_crop(self.crop, self.root)

    def test_local_config_symlink_refused(self):
        target = self.root / "outside.json"
        target.write_text(json.dumps({"api_key": DUMMY_KEY}))
        path = self.root / api.LOCAL_CONFIG
        path.parent.mkdir()
        path.symlink_to(target)
        with self.assertRaises(api.ReviewAPIError):
            api.load_review_config(self.root)

    def test_explicit_qwen_dispatch_preserves_local_path_without_api_call(self):
        self.config(provider="qwen_local")
        with patch.object(region, "_qwen_backend_status", return_value={"ready": False, "error": "offline"}), patch.object(api, "build_opener", side_effect=AssertionError("API")):
            status = region.backend_status(self.root)
            self.assertFalse(status["ready"])
            self.assertEqual(status["provider"], "qwen_local")
        with patch.object(region, "_classify_crop_qwen", return_value={"local": True}) as local:
            self.assertEqual(region.classify_crop(self.crop, self.root), {"local": True})
            local.assert_called_once_with(self.crop, self.root)


if __name__ == "__main__":
    unittest.main()
