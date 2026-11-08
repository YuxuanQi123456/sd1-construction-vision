"""Summary transport tests against localhost fixtures; no real service or Key."""
import base64
from http.client import BadStatusLine
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

APP = Path(__file__).resolve().parents[1] / "sitewatch/app"
sys.path.insert(0, str(APP))
import review_api as api
from test_review_api import DUMMY_KEY, PNG, fixture_server, response


class SummaryAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sd1-summary-api-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = [self.root / f"input-{number}.png" for number in range(3)]
        self.image_bytes = [PNG, b"\xff\xd8\xfffixture-jpeg", PNG]
        for image, content in zip(self.images, self.image_bytes):
            image.write_bytes(content)

    def config(self, **values):
        config = {**api.DEFAULT_CONFIG, "api_key": DUMMY_KEY, **values}
        path = self.root / api.LOCAL_CONFIG
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(config), encoding="utf-8")
        return config

    def test_single_and_three_images_exact_payload_and_one_http_request(self):
        for count in (1, 3):
            with self.subTest(count=count):
                with fixture_server(response('{"overview":"可见现场"}')) as (url, requests):
                    self.config(base_url=url)
                    result = api.request_image_summary(self.images[:count], self.root, "固定总结提示")
                self.assertEqual(len(requests), 1)
                request = requests[0]
                self.assertEqual(request["path"], "/v1/responses")
                self.assertEqual(request["headers"]["Authorization"], "Bearer " + DUMMY_KEY)
                payload = json.loads(request["body"])
                self.assertEqual(set(payload), {"model", "reasoning", "store", "max_output_tokens", "input"})
                self.assertEqual(payload["model"], "gpt-6.1-sol")
                self.assertEqual(payload["reasoning"], {"effort": "max"})
                self.assertIs(payload["store"], False)
                self.assertEqual(payload["max_output_tokens"], 4096)
                self.assertEqual(len(payload["input"]), 1)
                content = payload["input"][0]["content"]
                self.assertEqual(content[0], {"type": "input_text", "text": "固定总结提示"})
                self.assertEqual(len(content), count + 1)
                for index, item in enumerate(content[1:]):
                    self.assertEqual(item["type"], "input_image")
                    self.assertEqual(item["detail"], "high")
                    mime = "image/jpeg" if index == 1 else "image/png"
                    self.assertTrue(item["image_url"].startswith(f"data:{mime};base64,"))
                    self.assertEqual(base64.b64decode(item["image_url"].split(",", 1)[1]), self.image_bytes[index])
                self.assertEqual(result["raw_answer"], '{"overview":"可见现场"}')
                self.assertEqual(result["api"], ["POST /responses"])
                self.assertTrue(result["fresh_session"])
                self.assertTrue(result["backend"]["connectivity_verified"])
                self.assertEqual(result["usage"]["total_tokens"], 15)
                self.assertGreaterEqual(result["elapsed_seconds"], 0)
                self.assertNotIn(DUMMY_KEY, json.dumps(result))
        self.assertEqual([image.read_bytes() for image in self.images], self.image_bytes)

    def test_supplied_config_snapshot_is_used_without_reread(self):
        with fixture_server() as (url, requests):
            snapshot = self.config(base_url=url, model="snapshot-model", reasoning_effort="high", max_output_tokens=500)
            self.config(base_url="http://127.0.0.1:1/v1", model="changed-model", reasoning_effort="low")
            with patch.object(api, "load_review_config", side_effect=AssertionError("config reread")):
                result = api.request_image_summary(self.images, self.root, "总结", _config=snapshot)
        payload = json.loads(requests[0]["body"])
        self.assertEqual(payload["model"], "snapshot-model")
        self.assertEqual(payload["reasoning"]["effort"], "high")
        self.assertEqual(payload["max_output_tokens"], 500)
        self.assertEqual(result["backend"]["model"], payload["model"])
        self.assertEqual(result["backend"]["reasoning_effort"], payload["reasoning"]["effort"])
        self.assertEqual(len(requests), 1)

    def test_invalid_count_path_image_or_prompt_never_creates_transport(self):
        self.config()
        bad = self.root / "invalid.png"
        bad.write_bytes(b"not an image")
        cases = [([], "总结"), (self.images * 2, "总结"), (str(self.images[0]), "总结"),
                 ([self.root / "missing.png"], "总结"), ([bad], "总结"), ([None], "总结"),
                 ([self.images[0]], ""), ([self.images[0]], None)]
        with patch.object(api, "build_opener", side_effect=AssertionError("network")):
            for images, prompt in cases:
                with self.subTest(images=str(images), prompt=prompt):
                    with self.assertRaises(api.ReviewAPIError) as caught:
                        api.request_image_summary(images, self.root, prompt)
                    self.assertNotIn(DUMMY_KEY, str(caught.exception))

    def test_per_image_and_total_limits_precede_network(self):
        self.config()
        with patch.object(api, "build_opener", side_effect=AssertionError("network")):
            with patch.object(api, "MAX_SUMMARY_IMAGE_BYTES", len(PNG) - 1):
                with self.assertRaisesRegex(api.ReviewAPIError, "单张"):
                    api.request_image_summary([self.images[0]], self.root, "总结")
            with patch.object(api, "MAX_SUMMARY_TOTAL_BYTES", len(PNG)):
                with self.assertRaisesRegex(api.ReviewAPIError, "总大小"):
                    api.request_image_summary(self.images, self.root, "总结")

    def test_missing_key_and_removed_provider_never_create_transport(self):
        with patch.object(api, "build_opener", side_effect=AssertionError("network")):
            self.config(api_key="")
            with self.assertRaisesRegex(api.ReviewAPIError, "Key"):
                api.request_image_summary(self.images, self.root, "总结")
            self.config(provider="qwen_local")
            with self.assertRaisesRegex(api.ReviewAPIError, "仅支持 openai"):
                api.request_image_summary(self.images, self.root, "总结")

    def test_reflected_key_and_untrusted_response_fields_are_not_returned(self):
        data = response("总结 " + DUMMY_KEY, id="r-" + DUMMY_KEY, model="m-" + DUMMY_KEY)
        data["request"] = {"api_key": DUMMY_KEY}
        data["usage"]["secret"] = DUMMY_KEY
        data["usage"]["output_tokens_details"]["api_key"] = DUMMY_KEY
        with fixture_server(data) as (url, requests):
            self.config(base_url=url)
            result = api.request_image_summary(self.images, self.root, "总结")
        self.assertNotIn(DUMMY_KEY, json.dumps(result))
        self.assertNotIn("request", result)
        self.assertEqual(result["usage"], {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15,
                                         "output_tokens_details": {"reasoning_tokens": 2}})
        self.assertEqual(len(requests), 1)

    def test_incomplete_refusal_malformed_and_oversized_responses_fail_once(self):
        refused = response()
        refused["output"][0]["content"] = [{"type": "refusal", "refusal": DUMMY_KEY}]
        cases = [response(status="incomplete"), refused, response(output=[]),
                 response(error={"message": DUMMY_KEY}), b"not-json"]
        for reply in cases:
            with self.subTest(reply=str(reply)[:80]):
                with fixture_server(reply) as (url, requests):
                    self.config(base_url=url)
                    with self.assertRaises(api.ReviewAPIError) as caught:
                        api.request_image_summary(self.images, self.root, "总结")
                self.assertEqual(len(requests), 1)
                self.assertNotIn(DUMMY_KEY, str(caught.exception))
        with fixture_server(b" " * 65) as (url, requests):
            self.config(base_url=url)
            with patch.object(api, "MAX_RESPONSE_BYTES", 64):
                with self.assertRaisesRegex(api.ReviewAPIError, "响应过大"):
                    api.request_image_summary(self.images, self.root, "总结")
        self.assertEqual(len(requests), 1)

    def test_redirect_is_not_followed_and_error_body_is_not_reflected(self):
        with fixture_server() as (sink, received):
            with fixture_server(b"", status=302, headers={"Location": sink + "/responses"}) as (url, sent):
                self.config(base_url=url)
                with self.assertRaisesRegex(api.ReviewAPIError, "重定向"):
                    api.request_image_summary(self.images, self.root, "总结")
        self.assertEqual(len(sent), 1)
        self.assertEqual(received, [])
        with fixture_server({"error": {"message": DUMMY_KEY}}, status=401) as (url, sent):
            self.config(base_url=url)
            with self.assertRaises(api.ReviewAPIError) as caught:
                api.request_image_summary(self.images, self.root, "总结")
        self.assertEqual(len(sent), 1)
        self.assertIn("401", str(caught.exception))
        self.assertNotIn(DUMMY_KEY, str(caught.exception))

    def test_timeout_protocol_and_network_errors_are_safe_and_not_retried(self):
        self.config()
        for error in (TimeoutError(DUMMY_KEY), BadStatusLine(DUMMY_KEY), URLError(DUMMY_KEY)):
            with self.subTest(error=type(error).__name__):
                opener = unittest.mock.Mock()
                opener.open.side_effect = error
                with patch.object(api, "build_opener", return_value=opener):
                    with self.assertRaises(api.ReviewAPIError) as caught:
                        api.request_image_summary(self.images, self.root, "总结")
                self.assertEqual(opener.open.call_count, 1)
                self.assertNotIn(DUMMY_KEY, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
