import threading
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pytest

from capper_monitor.app import App
from capper_monitor.calibration import CalibrationError
from capper_monitor.camera.base import CameraBackend
from capper_monitor.config import RoiConfig, load_config
from capper_monitor.detection.alignment_check import AlignmentCheckResult
from capper_monitor.detection.baseline_diff import BaselineDiffDetector
from capper_monitor.detection.roi import RoiFractional
from tests.helpers import add_noise, draw_line_in_roi, make_frame

CONFIG_YAML = """
camera:
  backend: opencv
detection:
  strategy: baseline_diff
  fallback_strategy: edge_density
  roi:
    x: 0.3
    y: 0.4
    w: 0.4
    h: 0.2
  baseline_diff:
    num_calibration_frames: 5
    density_threshold: 0.05
    reference_path: baseline_reference.npy
  debounce:
    on_delay_ms: 0
    off_delay_ms: 0
  alignment_check:
    enabled: true
    roi:
      x: 0.0
      y: 0.0
      w: 0.2
      h: 0.2
    reference_path: alignment_reference.npy
  refill_detection:
    enabled: false
gpio:
  pin_factory: mock
  alarm_output:
    pin: 17
  reset_button:
    pin: 27
    bounce_time_ms: 0
  plc_reset_input:
    pin: 22
    bounce_time_ms: 0
app:
  loop_interval_ms: 1
  lock_file_path: {lock_path}
  watchdog_enabled: false
web:
  enabled: true
  calibration_enabled: true
logging:
  console: false
  file_path: null
"""


class FakeCamera(CameraBackend):
    def __init__(self, frames: Iterable[Optional[np.ndarray]]):
        self._frames = iter(frames)

    def open(self) -> None:
        pass

    def read(self) -> Optional[np.ndarray]:
        return next(self._frames, None)

    def close(self) -> None:
        pass


class AlwaysFailingAlignmentChecker:
    is_ready = True

    def check(self, frame):
        return AlignmentCheckResult(ok=False, correlation=0.1)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_YAML.format(lock_path=str(tmp_path / "lock")), encoding="utf-8")
    return path


@pytest.fixture
def app(config_path):
    app = App(load_config(config_path), config_path=config_path)
    yield app
    app.gpio.close()


def full_frames(n=20):
    return [add_noise(make_frame(), sigma=3.0, seed=i) for i in range(n)]


def test_new_roi_falls_back_until_baseline_is_captured(app):
    app._handle_command("set_roi", make_frame(), x=0.2, y=0.3, w=0.5, h=0.3)
    assert app._detection_cfg.roi == RoiConfig(x=0.2, y=0.3, w=0.5, h=0.3)
    assert app.detector.strategy_name == "edge_density"


def test_invalid_roi_is_rejected(app):
    with pytest.raises(CalibrationError):
        app._handle_command("set_roi", make_frame(), x=0.8, y=0.1, w=0.5, h=0.2)


def test_threshold_out_of_range_is_rejected(app):
    with pytest.raises(CalibrationError):
        app._handle_command("set_threshold", make_frame(), value=1.5)


def test_save_requires_baseline_when_strategy_is_baseline_diff(app):
    with pytest.raises(CalibrationError):
        app._handle_command("save", make_frame())


def test_full_phone_workflow_survives_restart(app, config_path):
    frames = full_frames()
    app.camera = FakeCamera(frames)

    app._handle_command("set_roi", frames[0], x=0.25, y=0.35, w=0.5, h=0.3)
    app._handle_command("capture_baseline", frames[0])
    assert isinstance(app.detector, BaselineDiffDetector) and app.detector.is_ready
    app._handle_command("capture_alignment", frames[0])
    app._handle_command("set_threshold", frames[0], value=0.04)
    app._handle_command("save", frames[0])

    assert (Path(config_path).parent / "baseline_reference.npy").is_file()
    assert (Path(config_path).parent / "alignment_reference.npy").is_file()

    reloaded = load_config(config_path)
    assert reloaded.detection.roi == RoiConfig(x=0.25, y=0.35, w=0.5, h=0.3)
    assert reloaded.detection.baseline_diff.density_threshold == 0.04

    restarted = App(reloaded, config_path=config_path)
    try:
        assert isinstance(restarted.detector, BaselineDiffDetector) and restarted.detector.is_ready
        roi = RoiFractional(0.25, 0.35, 0.5, 0.3)
        assert restarted.detector.detect(add_noise(make_frame(), sigma=3.0, seed=99)).line_visible is False
        with_line = draw_line_in_roi(add_noise(make_frame(), sigma=3.0, seed=99), roi, thickness=4)
        assert restarted.detector.detect(with_line).line_visible is True
    finally:
        restarted.gpio.close()


def test_main_loop_executes_command_from_web_thread(app):
    app.camera = FakeCamera(full_frames(50))
    results = {}

    def submitter():
        results["value"] = app._commands.submit("set_threshold", value=0.07)

    thread = threading.Thread(target=submitter)
    thread.start()
    for _ in range(40):
        if not thread.is_alive():
            break
        app._tick()
        thread.join(timeout=0.01)

    assert not thread.is_alive()
    assert "message" in results["value"]
    assert app.detector.threshold == 0.07


def test_stream_keeps_updating_during_camera_misalignment(app):
    app.alignment_checker = AlwaysFailingAlignmentChecker()
    app._process_frame(make_frame())

    assert app.frame_buffer.get_frame() is not None
    status = app.frame_buffer.get_status()
    assert status["reason"] == "camera_misalignment"
    assert status["alignment_correlation"] == 0.1
    assert status["calibration_enabled"] is True
