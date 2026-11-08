"""Summary evidence, strict model output and independent human decisions."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

import cv2
import numpy as np

APP = Path(__file__).resolve().parents[1] / "sitewatch/app"
sys.path.insert(0, str(APP))
import review_api as api
import safety_summary as summary
from review_evidence import evidence_zip
from test_review_api import DUMMY_KEY, fixture_server, response


def answer(positions=None, count=1):
    return {"overview": "采样画面可见施工人员，疑似情况需人工核查。", "observations": ["可见人员和施工场景"],
            "limitations": ["仅分析本次采样画面，看不清的装备无法判断。"],
            "findings": [{"title": "疑似防护装备不清", "detail": "画面中头部细节不清，需人工核查。",
                          "suggestion": "结合现场核查装备佩戴情况。", "frame_positions": positions or [0]}
                         for _ in range(count)]}


def process_decision(review_dir, summary_id, finding_id, event, queue):
    queue.put("ready")
    event.wait(20)
    try:
        summary.set_finding_decision(review_dir, summary_id, finding_id, "confirmed", finding_id)
        queue.put("saved")
    except Exception as exc:
        queue.put(type(exc).__name__)


class SafetySummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sd1-safety-summary-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.review = self.root / "review"
        self.review.mkdir()
        self.config()
        self.prepare()

    def config(self, **values):
        config = {**api.DEFAULT_CONFIG, "api_key": DUMMY_KEY, **values}
        path = self.root / api.LOCAL_CONFIG
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(config), encoding="utf-8")
        return config

    def prepare(self, count=1, dimensions=(48, 32), detections=True):
        frames = []
        for position in range(count):
            filename = f"frame-{position * 30:06d}-input.png"
            pixels = np.full((dimensions[1], dimensions[0], 3), position * 9, dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(self.review / filename), pixels))
            frames.append({"input_file": filename, "frame_index": position * 30,
                           "timestamp_seconds": float(position),
                           "detections": [{"class_name": "Hardhat", "confidence": .72,
                                           "bbox": [0, 0, 20, 20], "private": "not-context"}] if detections else []})
        data = {"status": "complete", "source_name": "DO-NOT-SEND-expected-answer-title",
                "source_provenance": {"author": "DO-NOT-SEND-author"},
                "model": {"id": "fixture-detector"}, "frames": frames}
        (self.review / "detections.json").write_text(json.dumps(data), encoding="utf-8")
        return data

    def generate(self, value=None):
        value = answer() if value is None else value
        opinion = {"raw_answer": json.dumps(value, ensure_ascii=False), "backend": {"model": "fixture-model"},
                   "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}, "elapsed_seconds": .1}
        with patch.object(summary, "request_image_summary", return_value=opinion) as request:
            view = summary.generate_summary(self.review, self.root)
        return view, request

    def snapshot_inputs(self):
        return {file.name: hashlib.sha256(file.read_bytes()).hexdigest()
                for file in self.review.iterdir() if file.is_file()}

    def test_single_image_real_http_pending_server_evidence_and_zero_read_requests(self):
        before = self.snapshot_inputs()
        with fixture_server(response(json.dumps(answer(), ensure_ascii=False))) as (url, requests):
            self.config(base_url=url)
            view = summary.generate_summary(self.review, self.root)
            status = summary.summary_backend_status(self.root)
            self.assertTrue(status["ready"])
            self.assertFalse(status["connectivity_verified"])
            self.assertEqual(status["max_output_tokens"], 8192)
            self.assertEqual(summary.load_summary(self.review), view)
            self.assertEqual(summary.latest_summary_attempt(self.review)["status"], "complete")
            report = summary.summary_report(self.review)
            self.assertEqual(len(requests), 1)
        self.assertEqual(before, self.snapshot_inputs())
        finding = view["findings"][0]
        self.assertRegex(view["summary_id"], r"^summary-[a-f0-9]{32}$")
        self.assertEqual(finding["id"], "finding-01")
        self.assertEqual(finding["review_status"], "pending")
        self.assertEqual(finding["review_note"], "")
        self.assertIsNone(finding["reviewed_at"])
        self.assertEqual(finding["evidence"], [{"frame_position": 0, "frame_index": 0,
                                              "timestamp_seconds": 0.0, "input_file": "frame-000000-input.png"}])
        self.assertIn("待人工确认", report)
        self.assertNotIn("openai", report.lower())
        record = summary.latest_summary_attempt(self.review)
        self.assertEqual(record["request_backend"]["model"], "gpt-6.1-sol")
        self.assertEqual(record["request_backend"]["max_output_tokens"], 8192)
        self.assertEqual(record["opinion"]["backend"]["max_output_tokens"], 8192)
        self.assertEqual(record["opinion"]["usage"]["total_tokens"], 15)
        self.assertNotIn(DUMMY_KEY, json.dumps(record))
        payload = json.loads(requests[0]["body"])
        prompt = payload["input"][0]["content"][0]["text"]
        self.assertNotIn("DO-NOT-SEND", prompt)
        self.assertNotIn("not-context", prompt)
        self.assertEqual(record["prompt"], prompt)
        uri = payload["input"][0]["content"][1]["image_url"]
        preview = self.review / record["inputs"][0]["preview_file"]
        self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), preview.read_bytes())

    def test_multi_frame_selection_scope_resize_and_sha_without_original_changes(self):
        self.prepare(count=8, dimensions=(1920, 1080))
        before = self.snapshot_inputs()
        view, request = self.generate(answer([0, 4, 7]))
        self.assertEqual(view["scope"], {"detected_frame_count": 8, "summary_frame_positions": [0, 4, 7],
                                        "timestamps_seconds": [0.0, 4.0, 7.0]})
        request.assert_called_once()
        self.assertEqual(len(request.call_args.args[0]), 3)
        context = json.loads(request.call_args.args[2].removeprefix(summary.PROMPT))
        self.assertEqual(context[0]["bbox_coordinate_basis"], "original_unannotated_frame")
        self.assertEqual(context[0]["input_dimensions_wh"], [1920, 1080])
        self.assertEqual(context[0]["preview_dimensions_wh"], [1280, 720])
        for item in summary.latest_summary_attempt(self.review)["inputs"]:
            self.assertEqual(item["input_dimensions_wh"], [1920, 1080])
            self.assertEqual(item["preview_dimensions_wh"], [1280, 720])
            self.assertEqual(hashlib.sha256((self.review / item["preview_file"]).read_bytes()).hexdigest(), item["preview_sha256"])
            self.assertEqual(before[item["input_file"]], item["input_sha256"])
        self.assertEqual(before, self.snapshot_inputs())

    def test_two_frames_are_unique_and_zero_findings_allowed_without_head_detections(self):
        self.prepare(count=2, detections=False)
        view, request = self.generate(answer(count=0))
        self.assertEqual(view["scope"]["summary_frame_positions"], [0, 1])
        self.assertEqual(view["findings"], [])
        self.assertEqual(len(request.call_args.args[0]), 2)
        self.assertIn("仍需人工", summary.summary_report(self.review))

    def test_parser_accepts_only_plain_json_or_one_json_fence(self):
        raw = json.dumps(answer())
        for value in (raw, "```json\n" + raw + "\n```", "```\n" + raw + "\n```"):
            self.assertEqual(summary._parse_answer(value, [0])["overview"], answer()["overview"])
        for value in ("正文\n" + raw, raw + "\n附注", "```json\n" + raw + "\n```\nother", "null",
                      '{"overview":"one","overview":"two"}', "{\"x\":NaN}"):
            with self.subTest(value=value[:30]), self.assertRaises(summary.SafetySummaryError):
                summary._parse_answer(value, [0])

    def test_schema_rejects_types_limits_arbitrary_paths_and_ai_confirmations(self):
        invalid = []
        for key, value in (("overview", ""), ("overview", 4), ("overview", "x" * 2001),
                           ("observations", ["x"] * 9), ("observations", [""]),
                           ("limitations", "text"), ("findings", [answer()["findings"][0]] * 7)):
            item = answer()
            item[key] = value
            invalid.append(item)
        for key, value in (("id", "evil"), ("review_status", "confirmed"), ("input_file", "../../secret"),
                           ("title", ""), ("detail", None), ("suggestion", "x" * 801),
                           ("frame_positions", [1]), ("frame_positions", [True]),
                           ("frame_positions", [0, 0]), ("frame_positions", []),
                           ("frame_positions", ["../../secret"])):
            item = answer()
            item["findings"][0][key] = value
            invalid.append(item)
        invalid.append({**answer(), "summary_id": "external-id"})
        for value in invalid:
            with self.subTest(value=str(value)[:70]), self.assertRaises(summary.SafetySummaryError):
                summary._parse_answer(json.dumps(value), [0])

    def test_invalid_ai_answer_saved_as_failed_and_no_success_created(self):
        with patch.object(summary, "request_image_summary", return_value={"raw_answer": '{"bad":"value"}'}) as request:
            with self.assertRaises(summary.SafetySummaryError):
                summary.generate_summary(self.review, self.root)
        request.assert_called_once()
        self.assertIsNone(summary.load_summary(self.review))
        failure = summary.latest_summary_attempt(self.review)
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(failure["opinion"]["raw_answer"], '{"bad":"value"}')

    def test_invalid_unicode_text_is_rejected_and_failure_evidence_still_persists(self):
        value = answer()
        value["overview"] = "broken-\ud800"
        for ascii_escaped in (True, False):
            raw = json.dumps(value, ensure_ascii=ascii_escaped)
            with self.subTest(ascii_escaped=ascii_escaped), patch.object(summary, "request_image_summary", return_value={"raw_answer": raw}):
                with self.assertRaisesRegex(summary.SafetySummaryError, "Unicode"):
                    summary.generate_summary(self.review, self.root)
            self.assertIsNone(summary.load_summary(self.review))
            failure = summary.latest_summary_attempt(self.review)
            self.assertEqual(failure["status"], "failed")
            self.assertEqual(failure["opinion"]["raw_answer"], raw)
        view, _ = self.generate()
        with self.assertRaises(summary.SafetySummaryError):
            summary.set_finding_decision(self.review, view["summary_id"], "finding-01", "confirmed", "broken-\ud800")
        self.assertEqual(summary.load_summary(self.review), view)

    def test_three_manual_states_persist_without_mutating_ai_and_history_is_separate(self):
        view, _ = self.generate()
        base = self.review / "safety-summary"
        original = {path: path.read_bytes() for path in base.rglob("summary.json")}
        original[base / "latest-success.json"] = (base / "latest-success.json").read_bytes()
        with patch.object(summary, "request_image_summary", side_effect=AssertionError("network")):
            for status in ("confirmed", "dismissed", "pending"):
                updated = summary.set_finding_decision(self.review, view["summary_id"], "finding-01", status, "人工核查 " + status)
                self.assertEqual(updated, summary.load_summary(self.review))
                self.assertEqual(updated["findings"][0]["review_status"], status)
                self.assertIn("人工核查 " + status, summary.summary_report(self.review))
                self.assertTrue(updated["findings"][0]["reviewed_at"])
        for path, content in original.items():
            self.assertEqual(path.read_bytes(), content)
        decisions = json.loads(next((base / "decisions").glob("*.json")).read_text())
        self.assertEqual([item["status"] for item in decisions["history"]], ["confirmed", "dismissed", "pending"])
        self.assertNotIn("actor", decisions)

    def test_invalid_decision_versions_ids_states_and_notes_rejected(self):
        view, _ = self.generate()
        values = [("summary-" + "a" * 32, "finding-01", "pending", ""),
                  ("../secret", "finding-01", "pending", ""),
                  (view["summary_id"], "finding-02", "pending", ""),
                  (view["summary_id"], "../file", "pending", ""),
                  (view["summary_id"], "finding-01", "approved", ""),
                  (view["summary_id"], "finding-01", [], ""),
                  (view["summary_id"], "finding-01", "pending", "x" * 1001),
                  (view["summary_id"], "finding-01", "pending", 3)]
        for args in values:
            with self.subTest(args=str(args)[:70]), self.assertRaises(summary.SafetySummaryError):
                summary.set_finding_decision(self.review, *args)
        self.assertEqual(summary.load_summary(self.review), view)
        self.assertFalse((self.review / "safety-summary/decisions").exists())

    def test_regeneration_resets_decisions_and_rejects_old_version(self):
        first, _ = self.generate()
        summary.set_finding_decision(self.review, first["summary_id"], "finding-01", "confirmed", "旧版备注")
        second, _ = self.generate()
        self.assertNotEqual(first["summary_id"], second["summary_id"])
        self.assertEqual(second["findings"][0]["review_status"], "pending")
        self.assertEqual(second["findings"][0]["review_note"], "")
        with self.assertRaisesRegex(summary.SafetySummaryError, "版本已更新"):
            summary.set_finding_decision(self.review, first["summary_id"], "finding-01", "dismissed")
        self.assertEqual(len(list((self.review / "safety-summary/attempts").glob("*/summary.json"))), 2)

    def test_thread_concurrent_decisions_do_not_overwrite_other_findings(self):
        view, _ = self.generate(answer(count=6))
        def save(index):
            return summary.set_finding_decision(self.review, view["summary_id"], f"finding-{index:02d}", "confirmed", str(index))
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(save, range(1, 7)))
        current = summary.load_summary(self.review)
        self.assertEqual([item["review_note"] for item in current["findings"]], [str(n) for n in range(1, 7)])
        history = json.loads(next((self.review / "safety-summary/decisions").glob("*.json")).read_text())["history"]
        self.assertEqual(len(history), 6)

    def test_process_concurrent_decisions_share_file_lock(self):
        view, _ = self.generate(answer(count=2))
        context = multiprocessing.get_context("spawn")
        event, queue = context.Event(), context.Queue()
        workers = [context.Process(target=process_decision, args=(str(self.review), view["summary_id"], f"finding-{index:02d}", event, queue)) for index in (1, 2)]
        for worker in workers:
            worker.start()
        try:
            self.assertEqual([queue.get(timeout=20) for _ in workers], ["ready", "ready"])
            event.set()
            self.assertEqual([queue.get(timeout=20) for _ in workers], ["saved", "saved"])
        finally:
            for worker in workers:
                worker.join(20)
                if worker.is_alive():
                    worker.terminate()
                    worker.join()
        self.assertEqual([worker.exitcode for worker in workers], [0, 0])
        self.assertTrue(all(item["review_status"] == "confirmed" for item in summary.load_summary(self.review)["findings"]))

    def test_failed_new_attempt_keeps_success_decisions_report_and_safe_errors(self):
        view, _ = self.generate()
        view = summary.set_finding_decision(self.review, view["summary_id"], "finding-01", "confirmed", "已核查")
        report = summary.summary_report(self.review)
        before = self.snapshot_inputs()
        with patch.object(summary, "request_image_summary", side_effect=RuntimeError(DUMMY_KEY)) as request:
            with self.assertRaises(summary.SafetySummaryError) as caught:
                summary.generate_summary(self.review, self.root)
        request.assert_called_once()
        self.assertNotIn(DUMMY_KEY, str(caught.exception))
        self.assertEqual(summary.load_summary(self.review), view)
        self.assertEqual(summary.summary_report(self.review), report)
        self.assertEqual((self.review / "safety-summary/report.txt").read_text(), report)
        self.assertEqual(summary.latest_summary_attempt(self.review)["status"], "failed")
        self.assertEqual(before, self.snapshot_inputs())
        for file in (self.review / "safety-summary").rglob("*.json"):
            self.assertNotIn(DUMMY_KEY, file.read_text())

    def test_incomplete_and_refused_http_responses_keep_safe_usage_and_original_text(self):
        incomplete = response("partial " + DUMMY_KEY, status="incomplete", id="resp-" + DUMMY_KEY)
        refused = response()
        refused["output"][0]["content"] = [{"type": "refusal", "refusal": "refused " + DUMMY_KEY}]
        for reply, expected in ((incomplete, "partial"), (refused, "refused")):
            with self.subTest(expected=expected), fixture_server(reply) as (url, requests):
                self.config(base_url=url)
                with self.assertRaises(summary.SafetySummaryError):
                    summary.generate_summary(self.review, self.root)
            self.assertEqual(len(requests), 1)
            record = summary.latest_summary_attempt(self.review)
            self.assertEqual(record["status"], "failed")
            self.assertIn(expected, record["opinion"]["raw_answer"])
            self.assertEqual(record["opinion"]["usage"]["total_tokens"], 15)
            self.assertEqual(record["request_backend"]["max_output_tokens"], 8192)
            self.assertEqual(record["opinion"]["backend"]["max_output_tokens"], 8192)
            self.assertGreaterEqual(record["opinion"]["elapsed_seconds"], 0)
            self.assertGreaterEqual(record["elapsed_seconds"], 0)
            self.assertNotIn(DUMMY_KEY, json.dumps(record))

    def test_report_write_failure_leaves_human_state_and_report_unchanged(self):
        view, _ = self.generate()
        view = summary.set_finding_decision(self.review, view["summary_id"], "finding-01", "confirmed", "先前保存")
        base = self.review / "safety-summary"
        state_path = next((base / "decisions").glob("*.json"))
        state_before, report_before = state_path.read_bytes(), (base / "report.txt").read_bytes()
        write = summary._atomic_text
        def fail_report(path, text):
            if path.name == "report.txt":
                raise OSError(DUMMY_KEY)
            return write(path, text)
        with patch.object(summary, "_atomic_text", side_effect=fail_report):
            with self.assertRaisesRegex(summary.SafetySummaryError, "尚未保存") as caught:
                summary.set_finding_decision(self.review, view["summary_id"], "finding-01", "dismissed", "不应保存")
        self.assertNotIn(DUMMY_KEY, str(caught.exception))
        self.assertEqual(summary.load_summary(self.review), view)
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual((base / "report.txt").read_bytes(), report_before)

    def test_human_state_commit_failure_restores_previous_report(self):
        view, _ = self.generate()
        report = summary.summary_report(self.review)
        write = summary._atomic_json
        def fail_decision(path, value):
            if path.parent.name == "decisions":
                raise OSError(DUMMY_KEY)
            return write(path, value)
        with patch.object(summary, "_atomic_json", side_effect=fail_decision):
            with self.assertRaisesRegex(summary.SafetySummaryError, "尚未保存"):
                summary.set_finding_decision(self.review, view["summary_id"], "finding-01", "confirmed", "不应保存")
        self.assertEqual(summary.load_summary(self.review), view)
        self.assertEqual((self.review / "safety-summary/report.txt").read_text(), report)

    def test_generation_report_or_success_pointer_failure_preserves_old_success(self):
        view, _ = self.generate()
        report = summary.summary_report(self.review)
        text_write, json_write = summary._atomic_text, summary._atomic_json
        def fail_report(path, text):
            if path.name == "report.txt":
                raise OSError(DUMMY_KEY)
            return text_write(path, text)
        def fail_success(path, value):
            if path.name == "latest-success.json":
                raise OSError(DUMMY_KEY)
            return json_write(path, value)
        for name, failure in (("_atomic_text", fail_report), ("_atomic_json", fail_success)):
            with self.subTest(name=name), patch.object(summary, name, side_effect=failure):
                with self.assertRaisesRegex(summary.SafetySummaryError, "尚未保存"):
                    self.generate(answer(count=0))
            self.assertEqual(summary.load_summary(self.review), view)
            self.assertEqual((self.review / "safety-summary/report.txt").read_text(), report)
            failure_record = summary.latest_summary_attempt(self.review)
            self.assertEqual(failure_record["status"], "failed")
            self.assertIn("raw_answer", failure_record["opinion"])
            self.assertNotIn(DUMMY_KEY, json.dumps(failure_record))

    def test_export_lock_waits_for_human_transaction_and_repairs_stale_text(self):
        view, _ = self.generate()
        at_commit, release, exported = threading.Event(), threading.Event(), threading.Event()
        json_write = summary._atomic_json
        def pause_commit(path, value):
            if path.parent.name == "decisions":
                at_commit.set()
                if not release.wait(10):
                    raise AssertionError("test transaction not released")
            return json_write(path, value)
        def export():
            with summary.summary_export_lock(self.review):
                exported.set()
                with zipfile.ZipFile(evidence_zip(self.review)) as archive:
                    return archive.read("safety-summary/report.txt").decode()
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(summary, "_atomic_json", side_effect=pause_commit):
            saving = pool.submit(summary.set_finding_decision, self.review, view["summary_id"], "finding-01", "confirmed", "并发核查")
            try:
                self.assertTrue(at_commit.wait(10))
                exporting = pool.submit(export)
                self.assertFalse(exported.wait(.1), "export must wait for the state/report transaction")
            finally:
                release.set()
            saving.result(timeout=10)
            report = exporting.result(timeout=10)
        self.assertEqual(report, summary.summary_report(self.review))
        (self.review / "safety-summary/report.txt").write_text("stale")
        with summary.summary_export_lock(self.review):
            self.assertEqual((self.review / "safety-summary/report.txt").read_text(), summary._report(summary._load_unlocked(self.review / "safety-summary")))

    def test_export_lock_without_summary_is_read_only_and_failed_repair_rejects_export(self):
        with summary.summary_export_lock(self.review):
            self.assertFalse((self.review / "safety-summary").exists())
        self.generate()
        (self.review / "safety-summary/report.txt").write_text("stale")
        with patch.object(summary, "_atomic_text", side_effect=OSError(DUMMY_KEY)):
            with self.assertRaisesRegex(summary.SafetySummaryError, "无法同步"):
                with summary.summary_export_lock(self.review):
                    self.fail("stale evidence must not be exported")

    def test_invalid_input_paths_symlinks_missing_images_and_incomplete_detection_never_send(self):
        original = json.loads((self.review / "detections.json").read_text())
        outside = self.root / "outside.png"
        outside.write_bytes((self.review / original["frames"][0]["input_file"]).read_bytes())
        (self.review / "linked.png").symlink_to(outside)
        cases = []
        for filename in ("../outside.png", str(outside), "linked.png", "missing.png", "foo\\bar.png"):
            record = json.loads(json.dumps(original))
            record["frames"][0]["input_file"] = filename
            cases.append(record)
        cases.extend([{**original, "status": "processing"}, {**original, "frames": []}])
        for record in cases:
            (self.review / "detections.json").write_text(json.dumps(record))
            with self.subTest(record=str(record)[:70]), patch.object(summary, "request_image_summary", side_effect=AssertionError("network")) as request:
                with self.assertRaises(summary.SafetySummaryError):
                    summary.generate_summary(self.review, self.root)
                request.assert_not_called()

    def test_configuration_snapshot_and_reflected_key_are_scrubbed_from_every_artifact(self):
        original_snapshot = summary.review_backend_snapshot
        def change_config(config, root):
            safe = original_snapshot(config, root)
            self.config(model="changed-model", reasoning_effort="low", summary_max_output_tokens=500)
            return safe
        reply = answer()
        reply["overview"] += DUMMY_KEY
        with fixture_server(response(json.dumps(reply), model="server-" + DUMMY_KEY)) as (url, requests):
            self.config(base_url=url, max_output_tokens=4096, summary_max_output_tokens=10000)
            with patch.object(summary, "review_backend_snapshot", side_effect=change_config):
                view = summary.generate_summary(self.review, self.root)
        record = summary.latest_summary_attempt(self.review)
        payload = json.loads(requests[0]["body"])
        self.assertEqual(payload["model"], record["request_backend"]["model"])
        self.assertEqual(payload["reasoning"]["effort"], record["request_backend"]["reasoning_effort"])
        self.assertEqual(record["request_backend"]["model"], "gpt-6.1-sol")
        self.assertEqual(record["request_backend"]["max_output_tokens"], 10000)
        self.assertEqual(record["opinion"]["backend"]["max_output_tokens"], 10000)
        self.assertEqual(payload["max_output_tokens"], 10000)
        self.assertNotIn(DUMMY_KEY, json.dumps(view))
        for path in (self.review / "safety-summary").rglob("*"):
            if path.is_file() and path.suffix in {".json", ".txt"}:
                self.assertNotIn(DUMMY_KEY, path.read_text())

    def test_txt_and_existing_recursive_zip_include_current_decisions(self):
        view, _ = self.generate()
        view = summary.set_finding_decision(self.review, view["summary_id"], "finding-01", "dismissed", "画面复核已排除")
        report = summary.summary_report(self.review)
        self.assertEqual((self.review / "safety-summary/report.txt").read_text(), report)
        with zipfile.ZipFile(evidence_zip(self.review)) as archive:
            self.assertEqual(archive.read("safety-summary/report.txt").decode(), report)
            self.assertTrue(any(name.startswith("safety-summary/decisions/") for name in archive.namelist()))
            self.assertIn("detections.json", archive.namelist())

    def test_no_summary_and_distinct_review_directory_do_not_share_state(self):
        self.assertIsNone(summary.load_summary(self.review))
        self.assertIsNone(summary.latest_summary_attempt(self.review))
        self.assertIn("尚无", summary.summary_report(self.review))
        self.generate()
        other = self.root / "other"
        other.mkdir()
        self.assertIsNone(summary.load_summary(other))


if __name__ == "__main__":
    unittest.main()
