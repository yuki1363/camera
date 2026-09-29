from concurrent.futures import TimeoutError as FutureTimeoutError

from capper_monitor.calibration import CalibrationError
from capper_monitor.config import WebConfig
from capper_monitor.web.frame_buffer import FrameBuffer
from capper_monitor.web.server import create_app


class StubCommands:
    def __init__(self, error=None):
        self.calls = []
        self._error = error

    def submit(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self._error is not None:
            raise self._error
        return {"message": f"{name} done"}


def make_client(commands):
    return create_app(FrameBuffer(), WebConfig(), commands=commands).test_client()


def test_calibrate_page_renders():
    response = make_client(StubCommands()).get("/calibrate")
    assert response.status_code == 200
    assert "基準フレーム撮影".encode() in response.data


def test_api_is_forbidden_when_calibration_disabled():
    response = make_client(None).post("/api/save")
    assert response.status_code == 403
    assert response.get_json()["ok"] is False


def test_roi_is_forwarded_to_main_loop():
    commands = StubCommands()
    response = make_client(commands).post("/api/roi", json={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4})
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "message": "set_roi done"}
    assert commands.calls == [("set_roi", {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4})]


def test_invalid_roi_body_is_rejected_without_calling_main_loop():
    commands = StubCommands()
    response = make_client(commands).post("/api/roi", json={"x": "abc"})
    assert response.status_code == 400
    assert commands.calls == []


def test_threshold_and_capture_endpoints_map_to_commands():
    commands = StubCommands()
    client = make_client(commands)
    client.post("/api/threshold", json={"value": 0.05})
    client.post("/api/baseline")
    client.post("/api/alignment")
    client.post("/api/save")
    assert [name for name, _ in commands.calls] == [
        "set_threshold",
        "capture_baseline",
        "capture_alignment",
        "save",
    ]


def test_calibration_error_is_returned_as_message():
    commands = StubCommands(error=CalibrationError("基準フレームが未撮影です"))
    response = make_client(commands).post("/api/save")
    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "基準フレームが未撮影です"}


def test_timeout_is_reported_as_camera_problem():
    commands = StubCommands(error=FutureTimeoutError())
    response = make_client(commands).post("/api/baseline")
    assert response.status_code == 504
    assert response.get_json()["ok"] is False


def make_client_with(commands, **web):
    return create_app(FrameBuffer(), WebConfig(**web), commands=commands).test_client()


def test_motion_roi_and_ratio_are_forwarded():
    commands = StubCommands()
    client = make_client_with(commands)
    assert client.post("/api/motion_roi", json={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}).status_code == 200
    assert client.post("/api/motion_ratio", json={"value": 0.03}).status_code == 200
    assert commands.calls == [
        ("set_motion_roi", {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}),
        ("set_motion_ratio", {"value": 0.03}),
    ]


def test_invalid_motion_bodies_are_rejected():
    commands = StubCommands()
    client = make_client_with(commands)
    assert client.post("/api/motion_roi", json={"x": "a"}).status_code == 400
    assert client.post("/api/motion_ratio", json={}).status_code == 400
    assert commands.calls == []


def test_shutdown_is_forbidden_unless_enabled():
    commands = StubCommands()
    response = make_client_with(commands).post("/api/shutdown")
    assert response.status_code == 403
    assert commands.calls == []


def test_shutdown_is_forwarded_when_enabled():
    commands = StubCommands()
    response = make_client_with(commands, shutdown_enabled=True).post("/api/shutdown")
    assert response.status_code == 200
    assert commands.calls == [("shutdown", {})]


def test_shutdown_works_even_when_calibration_is_disabled():
    commands = StubCommands()
    client = make_client_with(commands, shutdown_enabled=True, calibration_enabled=False)
    assert client.post("/api/shutdown").status_code == 200
    assert client.post("/api/save").status_code == 403
    assert client.post("/api/motion_ratio", json={"value": 0.03}).status_code == 403
    assert commands.calls == [("shutdown", {})]


def test_calibrate_page_shows_shutdown_button_only_when_enabled():
    assert b'id="btn-shutdown"' not in make_client_with(StubCommands()).get("/calibrate").data
    page = make_client_with(StubCommands(), shutdown_enabled=True).get("/calibrate")
    assert b'id="btn-shutdown"' in page.data
