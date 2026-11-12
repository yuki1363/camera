import logging

import pytest

from capper_monitor.app import App
from capper_monitor.config import load_config
from capper_monitor.diagnose import run_diagnosis
from capper_monitor.io.gpio import create_gpio_resources
from tests.helpers import add_noise, make_frame
from tests.test_integration_calibration import CONFIG_YAML, AlwaysFailingAlignmentChecker, FakeCamera


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


def _events(caplog, name):
    return [r for r in caplog.records if r.getMessage().startswith(name)]


def test_misalignment_is_logged_once_not_every_frame(app, caplog):
    app.alignment_checker = AlwaysFailingAlignmentChecker()
    with caplog.at_level(logging.INFO):
        for _ in range(50):
            app._process_frame(make_frame())
    assert len(_events(caplog, "camera_misalignment_detected")) == 1


def test_misalignment_recovery_is_logged(app, caplog):
    failing = AlwaysFailingAlignmentChecker()
    app.alignment_checker = failing
    app._process_frame(make_frame())
    app.alignment_checker = None
    with caplog.at_level(logging.INFO):
        app.alignment_checker = type(
            "Ok", (), {"is_ready": True, "check": lambda self, f: type(failing.check(f))(ok=True, correlation=0.9)}
        )()
        app._process_frame(make_frame())
    assert len(_events(caplog, "camera_misalignment_cleared")) == 1


def test_stuck_reset_input_is_warned_and_shown_in_status(app, caplog, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("capper_monitor.app.time.monotonic", lambda: clock[0])
    app.gpio.plc_reset_input._button.pin.drive_low()
    with caplog.at_level(logging.INFO):
        for _ in range(4):
            app._process_frame(make_frame())
            clock[0] += 3.0
    assert len(_events(caplog, "reset_input_stuck")) == 1
    assert app.frame_buffer.get_status()["reset_active"] == "plc_reset_input"

    app.gpio.plc_reset_input._button.pin.drive_high()
    with caplog.at_level(logging.INFO):
        app._process_frame(make_frame())
    assert len(_events(caplog, "reset_input_released")) == 1
    assert app.frame_buffer.get_status()["reset_active"] is None


def test_short_reset_press_is_not_warned(app, caplog):
    app.gpio.reset_button._button.pin.drive_low()
    with caplog.at_level(logging.INFO):
        app._process_frame(make_frame())
    app.gpio.reset_button._button.pin.drive_high()
    app._process_frame(make_frame())
    assert not _events(caplog, "reset_input_stuck")


def _diagnose(config_path, frames, **kwargs):
    lines = []
    ng = run_diagnosis(
        load_config(config_path),
        config_path=str(config_path),
        camera=FakeCamera(frames),
        out=lines.append,
        sleep=lambda s: None,
        **kwargs,
    )
    return ng, "\n".join(lines)


def test_diagnose_healthy_setup_has_no_ng(config_path, mock_pin_factory):
    frames = [add_noise(make_frame(), sigma=3.0, seed=i) for i in range(30)]
    ng, text = _diagnose(config_path, frames, gpio_pin_factory=mock_pin_factory)
    assert ng == 0, text
    assert "映像を取得できました" in text


def test_diagnose_reports_dead_camera(config_path, mock_pin_factory):
    ng, text = _diagnose(config_path, [], gpio_pin_factory=mock_pin_factory)
    assert ng == 1
    assert "カメラから映像を取得できません" in text


def test_diagnose_reports_stuck_reset_input(config_path, mock_pin_factory, monkeypatch):
    from capper_monitor import diagnose

    def create_with_plc_reset_held(gpio_config, pin_factory=None):
        gpio = create_gpio_resources(gpio_config, pin_factory=pin_factory)
        mock_pin_factory.pin(22).drive_low()
        return gpio

    monkeypatch.setattr(diagnose, "create_gpio_resources", create_with_plc_reset_held)
    frames = [make_frame() for _ in range(30)]
    ng, text = _diagnose(config_path, frames, gpio_pin_factory=mock_pin_factory)
    assert ng == 1
    assert "PLCリセット入力（GPIO22）が入ったままです" in text


def test_diagnose_refuses_while_service_is_running(config_path, app, mock_pin_factory):
    app._lock.acquire()
    try:
        ng, text = _diagnose(config_path, [make_frame()], gpio_pin_factory=mock_pin_factory)
    finally:
        app._lock.release()
    assert ng == 1
    assert "サービスが動作中" in text
