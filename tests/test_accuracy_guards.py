import io
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

import cad_converter
import utils


PNG_BYTES = b"\x89PNG\r\n\x1a\nminimal-png-payload"


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class AccuracyGuardTests(unittest.TestCase):
    def test_single_image_calls_rewind_stream_and_detect_png_mime(self):
        uploaded = io.BytesIO(PNG_BYTES)
        uploaded.name = "drawing.png"
        uploaded.read()
        captured = {}

        def fake_chat_completion(req):
            captured["request"] = req
            return _FakeCompletion("ok")

        with mock.patch.object(utils, "_chat_completion", side_effect=fake_chat_completion):
            utils._call_vision_api(uploaded, "system", "question")

        image_url = captured["request"]["messages"][1]["content"][0]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertGreater(len(image_url.split(",", 1)[1]), 0)

    def test_history_path_rewinds_stream_and_uses_fresh_default_history(self):
        captured_histories = []

        def fake_with_history(image_file, system_prompt, question, chat_history, max_tokens=1400):
            chat_history.append({"role": "assistant", "content": "mutated"})
            captured_histories.append(chat_history)
            return "ok"

        with mock.patch.object(utils, "_call_vision_api_with_history", side_effect=fake_with_history):
            first = io.BytesIO(PNG_BYTES)
            first.name = "first.png"
            second = io.BytesIO(PNG_BYTES)
            second.name = "second.png"
            utils.analyze_drawing(first, "Q1")
            utils.analyze_drawing(second, "Q2")

        self.assertEqual(len(captured_histories), 2)
        self.assertIsNot(captured_histories[0], captured_histories[1])
        self.assertEqual(len(captured_histories[0]), 1)
        self.assertEqual(len(captured_histories[1]), 1)

        uploaded = io.BytesIO(PNG_BYTES)
        uploaded.name = "history.png"
        uploaded.read()
        captured = {}

        def fake_chat_completion(req):
            captured["request"] = req
            return _FakeCompletion("ok")

        with mock.patch.object(utils, "_chat_completion", side_effect=fake_chat_completion):
            utils._call_vision_api_with_history(
                uploaded,
                "system",
                "question",
                [{"role": "assistant", "content": "prior"}],
            )

        image_url = captured["request"]["messages"][-1]["content"][0]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))

    def test_generate_bom_excel_returns_positioned_bytes_buffer(self):
        buffer = utils.generate_bom_excel(
            {
                "assembly_name": "Actuator",
                "drawing_number": "DWG-42",
                "revision": "B",
                "date": "2026-03-29",
                "items": [
                    {
                        "item_no": 1,
                        "part_number": "PN-001",
                        "description": "Bracket",
                        "quantity": 2,
                        "material": "Steel",
                        "standard": "ISO 2768",
                        "finish": "Zinc",
                        "notes": "",
                    }
                ],
            }
        )

        self.assertIsInstance(buffer, io.BytesIO)
        self.assertEqual(buffer.tell(), 0)
        self.assertGreater(len(buffer.getvalue()), 0)

    def test_cloud_poll_checks_immediately_before_sleeping(self):
        events = []

        def fake_urlopen(*args, **kwargs):
            events.append("poll")
            return _FakeResponse({"status": "done", "success": True})

        def fail_sleep(seconds):
            events.append("sleep")
            raise AssertionError("sleep should not occur before the first poll result")

        with mock.patch("cad_converter.urllib.request.urlopen", side_effect=fake_urlopen):
            with mock.patch("cad_converter.time.sleep", side_effect=fail_sleep):
                result = cad_converter._cloud_poll("session-1", timeout=10)

        self.assertTrue(result["success"])
        self.assertEqual(events[0], "poll")

    def test_load_results_closes_all_files(self):
        root = Path(__file__).resolve().parent / "_tmp_accuracy_guard"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)

        try:
            (root / "status.json").write_text(json.dumps({"completed": True, "file": "part.step"}), encoding="utf-8")
            (root / "dimensions.json").write_text(json.dumps({"length": 10}), encoding="utf-8")
            (root / "front.png").write_bytes(PNG_BYTES)

            tracked_handles = []
            real_open = open

            def tracking_open(*args, **kwargs):
                handle = real_open(*args, **kwargs)
                tracked_handles.append(handle)
                return handle

            with mock.patch("cad_converter.open", side_effect=tracking_open, create=True):
                with mock.patch.object(cad_converter, "convert_to_2d_style", side_effect=lambda payload: payload):
                    with mock.patch.object(cad_converter, "annotate_with_dims", side_effect=lambda payload, dims, view: payload):
                        with mock.patch.object(cad_converter, "generate_pdf", return_value=b"%PDF-test"):
                            result = cad_converter.load_results(str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)

        self.assertTrue(result["ready"])
        self.assertTrue(tracked_handles)
        self.assertTrue(all(handle.closed for handle in tracked_handles))

    def test_multiview_standards_uses_all_views_and_clamps_scores(self):
        captured = {}
        fake_payload = {
            "overall_score": 145,
            "standard_detected": "BS 8888",
            "verdict": "conditional pass",
            "checks": [
                {
                    "category": "Views and Projections",
                    "status": "warning",
                    "score": -5,
                    "findings": ["Front, top, and side views provided"],
                    "violations": ["Projection marker missing"],
                }
            ],
            "critical_violations": [],
            "warnings": ["Projection marker missing"],
            "recommendations": ["Add projection symbol"],
            "summary": "Needs one standards fix.",
        }

        def fake_multi(image_bytes_list, *args, **kwargs):
            captured["views"] = image_bytes_list
            return json.dumps(fake_payload)

        with mock.patch.object(utils, "_call_vision_api_multi", side_effect=fake_multi):
            result = utils.check_drawing_standards_multiview(
                {
                    "side": PNG_BYTES,
                    "front": PNG_BYTES,
                    "isometric": b"",
                }
            )

        self.assertEqual([label for label, _ in captured["views"]], ["front", "side"])
        self.assertEqual(result["overall_score"], 100)
        self.assertEqual(result["verdict"], "CONDITIONAL PASS")
        self.assertEqual(result["checks"][0]["score"], 0)
        self.assertEqual(result["checks"][0]["status"], "WARNING")

    def test_batch_analysis_clamps_manufacturability_score(self):
        fake_payload = {
            "drawing_name": "Part A",
            "part_number": "P-1",
            "drawing_type": "Detail",
            "status": "Production Ready",
            "manufacturability_score": 999,
            "estimated_cost_usd": "12-20",
            "complexity": "Low",
            "critical_issues": [],
            "warnings": [],
            "missing_dimensions": False,
            "has_gdt": True,
            "material_specified": True,
            "tolerance_risk": "Low",
            "recommended_process": "CNC Milling",
            "summary": "Looks good.",
        }

        with mock.patch.object(utils, "_call_vision_api", return_value=json.dumps(fake_payload)):
            result = utils.batch_analyze_drawing(io.BytesIO(PNG_BYTES), filename="part-a.png")

        self.assertEqual(result["manufacturability_score"], 100)


if __name__ == "__main__":
    unittest.main()
