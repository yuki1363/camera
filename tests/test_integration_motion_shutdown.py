import pytest

from capper_monitor.app import App
from capper_monitor.calibration import CalibrationError
from capper_monitor.config import RoiConfig, load_config
from tests.helpers import make_frame
from tests.test_integration_calibration import CONFIG_YAML

MOTION_YAML = CONFIG_YAML.replace(
    "  refill_detection:\n    enabled: false", "  refill_detection:\n    enabled: true"
).replace("  calibration_enabled: true", "  calibration_enabled: true\n  shutdown_enabled: true")


def make_app(tmp_path, yaml_text):
    path = tmp_path / "config.yaml"
    path.write_text(yaml_text.format(lock_path=str(tmp_path / "lock")), encoding="utf-8")
    return App(load_config(path), config_path=path), path


@pytest.fixture
def app(tmp_path):
    app, _ = make_app(tmp_path, MOTION_YAML)
    yield app
    app.gpio.close()


def test_motion_roi_and_ratio_commands_update_detector_and_config(app):
    app._handle_command("set_motion_roi", make_frame(), x=0.2, y=0.3, w=0.4, h=0.5)
    app._handle_command("set_motion_ratio", make_frame(), value=0.02)
    refill = app._detection_cfg.refill_detection
    assert refill.roi == RoiConfig(x=0.2, y=0.3, w=0.4, h=0.5)
    assert refill.motion_ratio == 0.02
    assert app.motion_detector.motion_ratio == 0.02


@pytest.mark.parametrize("value", [0.0, 1.0, 1.5])
def test_motion_ratio_out_of_range_is_rejected(app, value):
    with pytest.raises(CalibrationError):
        app._handle_command("set_motion_ratio", make_frame(), value=value)


def test_invalid_motion_roi_is_rejected(app):
    with pytest.raises(CalibrationError):
        app._handle_command("set_motion_roi", make_frame(), x=0.8, y=0.1, w=0.5, h=0.2)


def test_motion_settings_survive_save_and_reload(app, tmp_path):
    frame = make_frame()
    app._handle_command("set_motion_roi", frame, x=0.2, y=0.3, w=0.4, h=0.5)
    app._handle_command("set_motion_ratio", frame, value=0.02)
    app._handle_command("set_threshold", frame, value=0.04)
    app._handle_command("capture_alignment", frame)
    app._handle_command("capture_baseline", frame)
    app._handle_command("save", frame)
    refill = load_config(tmp_path / "config.yaml").detection.refill_detection
    assert refill.roi == RoiConfig(x=0.2, y=0.3, w=0.4, h=0.5)
    assert refill.motion_ratio == 0.02


def test_status_reports_motion_fields(app):
    app._process_frame(make_frame())
    app._publish(make_frame(), "test")
    status = app.frame_buffer.get_status()
    assert status["motion_enabled"] is True
    assert status["motion_threshold"] == 0.05
    assert status["motion_ratio"] == 0.0
    assert status["motion_peak"] == 0.0
    assert status["motion_roi"] is None
    assert status["shutdown_enabled"] is True


def test_shutdown_turns_output_off_then_powers_off(app):
    calls = []
    app._poweroff = lambda: calls.append(app.gpio.alarm_output.is_on)
    app.gpio.alarm_output.set(True)
    result = app._handle_command("shutdown", make_frame())
    assert calls == [False]  # 電源を切る時点でアラーム出力はOFF
    assert "シャットダウン" in result["message"]


def test_shutdown_failure_is_reported_and_output_stays_off(app):
    def deny():
        raise CalibrationError("シャットダウンを実行できませんでした")

    app._poweroff = deny
    with pytest.raises(CalibrationError, match="実行できませんでした"):
        app._handle_command("shutdown", make_frame())
    assert app.gpio.alarm_output.is_on is False


def test_shutdown_is_refused_when_disabled(tmp_path):
    app, _ = make_app(tmp_path, MOTION_YAML.replace("shutdown_enabled: true", "shutdown_enabled: false"))
    try:
        app._poweroff = lambda: pytest.fail("must not power off")
        with pytest.raises(CalibrationError):
            app._handle_command("shutdown", make_frame())
    finally:
        app.gpio.close()


def test_calibration_commands_are_refused_when_only_shutdown_is_enabled(tmp_path):
    app, _ = make_app(tmp_path, MOTION_YAML.replace("calibration_enabled: true", "calibration_enabled: false"))
    try:
        with pytest.raises(CalibrationError):
            app._handle_command("set_threshold", make_frame(), value=0.04)
        app._poweroff = lambda: None
        assert app._handle_command("shutdown", make_frame())["message"]
    finally:
        app.gpio.close()
