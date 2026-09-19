import threading
import time
from typing import Iterable, Optional

import numpy as np
import pytest

from capper_monitor.app import App
from capper_monitor.camera.base import CameraBackend
from capper_monitor.config import load_config
from capper_monitor.detection.roi import RoiFractional
from tests.helpers import draw_line_in_roi, make_frame

INTEGRATION_ROI = RoiFractional(0.3, 0.4, 0.4, 0.2)

INTEGRATION_CONFIG_YAML = """
camera:
  backend: opencv
detection:
  strategy: edge_density
  fallback_strategy: edge_density
  roi:
    x: 0.3
    y: 0.4
    w: 0.4
    h: 0.2
  edge_density:
    density_threshold: 0.03
    adaptive: false
  debounce:
    on_delay_ms: 0
    off_delay_ms: 0
  alignment_check:
    enabled: false
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
  fault_output:
    pin: 23
app:
  loop_interval_ms: 1
  lock_file_path: {lock_path}
  watchdog_enabled: false
  camera_retry:
    initial_backoff_ms: 1
    max_backoff_ms: 2
    fault_after_failures: 3
web:
  enabled: false
logging:
  console: false
  file_path: null
"""


class FakeCamera(CameraBackend):
    def __init__(self, frames: Iterable[Optional[np.ndarray]]):
        self._frames = iter(frames)
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def read(self) -> Optional[np.ndarray]:
        return next(self._frames, None)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def integration_config(tmp_path):
    lock_path = tmp_path / "capper-monitor.lock"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(INTEGRATION_CONFIG_YAML.format(lock_path=str(lock_path)), encoding="utf-8")
    return load_config(config_path)


def test_pipeline_processes_line_visible_and_clears(integration_config):
    app = App(integration_config)

    try:
        blank = make_frame()
        app._process_frame(blank)
        assert app.gpio.alarm_output.is_on is False

        with_line = draw_line_in_roi(make_frame(), INTEGRATION_ROI, thickness=6)
        app._process_frame(with_line)
        assert app.gpio.alarm_output.is_on is True

        app._process_frame(make_frame())
        assert app.gpio.alarm_output.is_on is False
    finally:
        app.gpio.close()


def test_camera_failure_triggers_fault_output(integration_config):
    app = App(integration_config)
    app.camera = FakeCamera([None, None, None, None])

    try:
        for _ in range(4):
            app._read_frame_with_retry()
        assert app.gpio.fault_output is not None
        assert app.gpio.fault_output.is_on is True

        # 復旧
        app.camera = FakeCamera([make_frame()])
        frame = app._read_frame_with_retry()
        assert frame is not None
        assert app.gpio.fault_output.is_on is False
    finally:
        app.gpio.close()


def test_run_shuts_down_safely_on_stop_signal(integration_config, mock_pin_factory):
    app = App(integration_config, gpio_pin_factory=mock_pin_factory)
    with_line = draw_line_in_roi(make_frame(), INTEGRATION_ROI, thickness=6)
    fake_camera = FakeCamera([with_line] * 200)
    app.camera = fake_camera

    alarm_pin = mock_pin_factory.pin(integration_config.gpio.alarm_output.pin)

    thread = threading.Thread(target=app.run, kwargs={"install_signal_handlers": False}, daemon=True)
    thread.start()

    deadline = time.monotonic() + 2.0
    while alarm_pin.state == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert alarm_pin.state == 1

    app._handle_stop_signal(None, None)
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert fake_camera.opened is True
    assert fake_camera.closed is True
    assert alarm_pin.state == 0
