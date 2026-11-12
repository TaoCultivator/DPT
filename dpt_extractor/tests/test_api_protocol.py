"""End-to-end tests for the headless DPT API protocol.

覆盖：服务层（load / extract / context / manual cursor / export）与 HTTP 壳
（/health、/rpc 成败分支、token 鉴权）。全部使用真实 .tss 样例，确保协议层
与 GUI 共用同一条提取路径，数值不会分叉。
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from dpt_extractor.api.serialization import result_to_dict
from dpt_extractor.api.server import create_server, start_in_thread
from dpt_extractor.api.service import ApiError, ApiService
from dpt_extractor.utils.sample_corpus import discover_sample_waveforms

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_ROOT = _PROJECT_ROOT / "示例文件"


def _pick_sample(*hints: str) -> Path:
    """Pick the first real .tss sample whose path contains every hint."""
    candidates = discover_sample_waveforms(_SAMPLE_ROOT)
    lowered = [(p, str(p).lower()) for p in candidates]

    if not hints:
        normal = [(p, text) for p, text in lowered if "short" not in text]
        if normal:
            lowered = normal

    for hint in hints:
        needle = hint.lower()
        matched = [p for p, text in lowered if needle in text]
        if matched:
            lowered = [(p, text) for p, text in lowered if p in matched]
    if not lowered:
        raise unittest.SkipTest(f"未找到包含 {hints} 的 .tss 样例")
    return lowered[0][0]


class _ServiceBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sample = _pick_sample()

    def setUp(self) -> None:
        self.service = ApiService()


class TestServiceHealth(_ServiceBase):
    def test_health_reports_identity_and_clean_state(self) -> None:
        health = self.service.health()
        self.assertTrue(health["ok"])
        self.assertEqual(health["service"], "dpt-extractor-api")
        self.assertFalse(health["loaded"])
        self.assertFalse(health["has_result"])

    def test_status_before_load_has_no_waveform_fields(self) -> None:
        status = self.service.status()
        self.assertNotIn("sample_count", status)
        self.assertEqual(status["state"], "idle")

    def test_unknown_command_raises_api_error(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            self.service.dispatch("no_such_command", {})
        self.assertEqual(ctx.exception.code, "unknown_command")


class TestServiceExtraction(_ServiceBase):
    def test_load_and_extract_returns_full_result(self) -> None:
        payload = self.service.load_session(self.sample)
        self.assertEqual(payload["source_path"], str(self.sample))
        self.assertGreater(payload["sample_count"], 0)
        result = payload["result"]
        self.assertIn("turn_off", result)
        self.assertIn("turn_on", result)
        self.assertIn("reverse_recovery", result)
        self.assertIn("segments_detail", result)
        # 数值必须来自真实提取，而不是空的默认 dataclass。
        self.assertNotEqual(result["vdc"], 0.0)

    def test_load_session_missing_file_raises(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            self.service.load_session(_PROJECT_ROOT / "no_such_file.tss")
        self.assertEqual(ctx.exception.code, "file_not_found")

    def test_extract_without_waveform_raises(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            self.service.run_extraction()
        self.assertEqual(ctx.exception.code, "no_waveform")

    def test_numpy_and_set_are_json_safe(self) -> None:
        payload = self.service.load_session(self.sample)["result"]
        # 不允许出现 NaN/Infinity 或无法序列化的对象。
        json.dumps(payload, allow_nan=False)
        self.assertIsInstance(payload["unavailable_metrics"], list)


class TestServiceContexts(_ServiceBase):
    def test_list_contexts_after_extraction(self) -> None:
        self.service.load_session(self.sample)
        contexts = self.service.list_contexts()
        self.assertIn("didt_contexts", contexts)
        self.assertTrue(contexts["didt_contexts"], "至少应有一个 di/dt 上下文")

    def test_get_context_returns_cursor(self) -> None:
        self.service.load_session(self.sample)
        contexts = self.service.list_contexts()
        section, name = contexts["dvdt_contexts"][0].split("/", 1)
        payload = self.service.get_context(section, name)
        self.assertEqual(payload["section"], section)
        self.assertEqual(payload["name"], name)
        self.assertIn("context", payload)

    def test_manual_cursor_recomputes_slope(self) -> None:
        self.service.load_session(self.sample)
        seg = self.service.get_result()["segments_detail"]["turn_on"]
        mid = (seg["t0_us"] + seg["t1_us"]) / 2.0
        updated = self.service.set_manual_cursor(
            "开通", "dv/dt", t_a_us=seg["t0_us"], t_b_us=mid
        )
        self.assertEqual(updated["section"], "开通")
        self.assertGreaterEqual(updated["value"], 0.0)
        self.assertEqual(updated["cursor"]["t_a_us"], seg["t0_us"])

    def test_manual_cursor_rejects_unsupported_metric(self) -> None:
        self.service.load_session(self.sample)
        with self.assertRaises(ApiError) as ctx:
            self.service.set_manual_cursor("开通", "Ton", t_a_us=1.0, t_b_us=2.0)
        self.assertEqual(ctx.exception.code, "unsupported_manual_cursor")

    def test_manual_cursor_rejects_degenerate_span(self) -> None:
        self.service.load_session(self.sample)
        with self.assertRaises(ApiError) as ctx:
            self.service.set_manual_cursor("开通", "dv/dt", t_a_us=5.0, t_b_us=5.0)
        self.assertEqual(ctx.exception.code, "invalid_cursor")

    def test_clear_manual_cursor(self) -> None:
        self.service.load_session(self.sample)
        seg = self.service.get_result()["segments_detail"]["turn_on"]
        self.service.set_manual_cursor(
            "开通", "dv/dt", t_a_us=seg["t0_us"], t_b_us=seg["t1_us"]
        )
        cleared = self.service.clear_manual_cursor("开通", "dv/dt")
        self.assertEqual(cleared["manual_cursors"], [])


class TestServiceSlopeRange(_ServiceBase):
    def test_set_slope_range_triggers_recalculation(self) -> None:
        self.service.load_session(self.sample)
        payload = self.service.set_slope_range(
            "关断过程", "dv/dt", start_pct=20.0, end_pct=80.0
        )
        self.assertEqual(payload["row_key"], "off_dvdt")
        self.assertEqual(payload["slope_ranges"]["off_dvdt"]["start_pct"], 20.0)
        self.assertIn("result", payload)

    def test_set_slope_range_rejects_non_slope_metric(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            self.service.set_slope_range("开通", "Ton", start_pct=1.0, end_pct=2.0)
        self.assertEqual(ctx.exception.code, "unknown_slope_metric")

    def test_auto_max_mode(self) -> None:
        payload = self.service.set_slope_range(
            "开通", "di/dt", auto_max=True, recalculate=False
        )
        self.assertEqual(
            payload["slope_ranges"]["on_didt"]["selection_mode"], "auto_max"
        )


class TestServiceExport(_ServiceBase):
    def test_export_xlsx_writes_real_file(self) -> None:
        import tempfile

        self.service.load_session(self.sample)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.xlsx"
            payload = self.service.export_xlsx(target)
            self.assertTrue(payload["exists"])
            self.assertGreater(payload["size_bytes"], 0)

    def test_export_without_result_raises(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            self.service.export_xlsx("whatever.xlsx")
        self.assertEqual(ctx.exception.code, "no_result")


class TestListSamples(_ServiceBase):
    def test_discovers_real_samples(self) -> None:
        payload = self.service.list_samples()
        self.assertGreater(payload["count"], 0)
        self.assertTrue(all(path.endswith(".tss") for path in payload["samples"]))


class TestHttpShell(_ServiceBase):
    def setUp(self) -> None:
        super().setUp()
        self.handle = start_in_thread(port=0, service=self.service)
        self.addCleanup(self.handle.stop)

    def _url(self, path: str) -> str:
        return f"{self.handle.base_url}{path}"

    def _post(self, command: str, params: dict | None = None) -> dict:
        body = json.dumps({"command": command, "params": params or {}}).encode()
        request = urllib.request.Request(
            self._url("/rpc"),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_health_endpoint(self) -> None:
        with urllib.request.urlopen(self._url("/health"), timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["service"], "dpt-extractor-api")

    def test_rpc_load_and_extract(self) -> None:
        payload = self._post("load_session", {"path": str(self.sample)})
        self.assertTrue(payload["ok"])
        self.assertGreater(payload["data"]["sample_count"], 0)
        self.assertIn("turn_off", payload["data"]["result"])

    def test_rpc_business_error_is_200_with_ok_false(self) -> None:
        payload = self._post("run_extraction")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "no_waveform")

    def test_rpc_unknown_command(self) -> None:
        payload = self._post("does_not_exist")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unknown_command")

    def test_rpc_missing_required_param(self) -> None:
        payload = self._post("get_context", {"section": "开通"})
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_param")


class TestHttpAuth(_ServiceBase):
    def test_token_required_when_configured(self) -> None:
        handle = start_in_thread(port=0, service=ApiService(), token="s3cret")
        self.addCleanup(handle.stop)
        body = json.dumps({"command": "health"}).encode()
        request = urllib.request.Request(
            f"{handle.base_url}/rpc",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unauthorized")

        request = urllib.request.Request(
            f"{handle.base_url}/rpc",
            data=body,
            headers={"Content-Type": "application/json", "X-DPT-Token": "s3cret"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])


class TestSerialization(unittest.TestCase):
    def test_result_to_dict_rejects_non_dataclass(self) -> None:
        with self.assertRaises(TypeError):
            result_to_dict({"not": "a dataclass"})


if __name__ == "__main__":
    unittest.main()