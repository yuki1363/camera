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


def feed_motion(app, ratios, step=1.0):
    """動き量の履歴（時刻, 比率）を直接入れる。"""
    from capper_monitor.detection.motion import MotionResult

    for i, ratio in enumerate(ratios):
        app._record_motion(MotionResult(motion_detected=False, ratio=ratio), now=100.0 + i * step)


def test_auto_motion_ratio_uses_twice_the_idle_peak(app):
    feed_motion(app, [0.01, 0.03, 0.02, 0.01])
    result = app._handle_command("auto_motion_ratio", make_frame())
    assert app._detection_cfg.refill_detection.motion_ratio == 0.06
    assert app.motion_detector.motion_ratio == 0.06
    assert "0.060" in result["message"]


def test_auto_motion_ratio_has_a_floor_and_a_ceiling(app):
    feed_motion(app, [0.0, 0.0, 0.0, 0.0])
    app._handle_command("auto_motion_ratio", make_frame())
    assert app.motion_detector.motion_ratio == 0.02
    feed_motion(app, [0.8, 0.9, 0.8, 0.9])
    app._handle_command("auto_motion_ratio", make_frame())
    assert app.motion_detector.motion_ratio == 0.9


def test_auto_motion_ratio_needs_a_few_seconds_of_samples(app):
    with pytest.raises(CalibrationError):
        app._handle_command("auto_motion_ratio", make_frame())
    feed_motion(app, [0.01], step=1.0)
    with pytest.raises(CalibrationError):
        app._handle_command("auto_motion_ratio", make_frame())


def test_state_machine_gets_stabilizer_values_from_config(app):
    assert app.state_machine._motion_hold_s == 3.0
    assert app.state_machine._motion_enter_s == 0.5


# --- 色マスク: テープの色の登録・赤判定の表示 ---

import cv2  # noqa: E402

# コード上の色マスク既定値は白用なので、実機のひな形と同じ赤の範囲を明示する
COLOR_YAML = MOTION_YAML.replace("strategy: baseline_diff", "strategy: color_mask").replace(
    "  baseline_diff:",
    "  color_mask:\n    hsv_lower: [170, 80, 60]\n    hsv_upper: [10, 255, 255]\n    pixel_ratio_threshold: 0.02\n  baseline_diff:",
)


def reddish_silver_with_tape():
    """赤みを帯びた銀色の面（ROIいっぱい）に赤テープが1本。"""
    frame = make_frame(color=(120, 125, 190))
    cv2.rectangle(frame, (150, 150), (330, 170), (20, 20, 215), -1)
    cv2.rectangle(frame, (0, 0), (40, 40), (190, 190, 190), -1)  # 色のついていない灰色の部分
    return frame


@pytest.fixture
def color_app(tmp_path):
    app, path = make_app(tmp_path, COLOR_YAML)
    yield app, path
    app.gpio.close()


def test_default_red_range_counts_reddish_silver_and_picking_the_tape_fixes_it(color_app):
    app, _ = color_app
    frame = reddish_silver_with_tape()
    app._handle_command("set_roi", frame, x=0.2, y=0.3, w=0.6, h=0.5)
    before = app.detector.detect(frame).score
    assert before > 0.5  # 実機と同じ症状: 銀色の面を赤として数えている

    result = app._handle_command("pick_color", frame, x=0.75, y=0.75, w=0.2, h=0.1)  # テープ上
    after = app.detector.detect(frame).score
    assert "登録しました" in result["message"]
    assert after < 0.2  # 銀色の面は数えず、テープだけ


def test_pick_color_needs_a_colored_sample(color_app):
    app, _ = color_app
    frame = reddish_silver_with_tape()
    with pytest.raises(CalibrationError):
        app._handle_command("pick_color", frame, x=0.0, y=0.0, w=0.1, h=0.1)  # 色の薄い範囲


def test_picked_color_is_saved_and_survives_reload(color_app):
    app, path = color_app
    frame = reddish_silver_with_tape()
    app._handle_command("set_roi", frame, x=0.2, y=0.3, w=0.6, h=0.5)
    app._handle_command("pick_color", frame, x=0.75, y=0.75, w=0.2, h=0.1)
    app._handle_command("capture_alignment", frame)
    app._handle_command("save", frame)
    saved = load_config(path).detection.color_mask
    assert saved.hsv_lower == app._detection_cfg.color_mask.hsv_lower
    assert saved.hsv_upper == app._detection_cfg.color_mask.hsv_upper


def test_pick_color_is_refused_for_other_strategies(app):
    with pytest.raises(CalibrationError):
        app._handle_command("pick_color", make_frame(), x=0.1, y=0.1, w=0.2, h=0.2)
    with pytest.raises(CalibrationError):
        app._handle_command("toggle_mask", make_frame())


def test_mask_view_and_status_report_the_color_info(color_app):
    app, _ = color_app
    frame = reddish_silver_with_tape()
    app._handle_command("set_roi", frame, x=0.2, y=0.3, w=0.6, h=0.5)
    app._process_frame(frame)
    app._handle_command("toggle_mask", frame)
    app._publish(frame, "test")
    status = app.frame_buffer.get_status()
    assert status["show_mask"] is True
    assert len(status["color_hsv"]) == 6
    assert status["roi_hsv"] is not None and len(status["roi_hsv"]) == 3
    # 赤判定の表示は映像だけを変え、検知の結果には影響しない
    assert app.detector.detect(frame).score > 0.5


def test_wobbling_score_near_threshold_does_not_flip_the_output(color_app):
    """スコアがしきい値付近で上下しても、出力（PLCへの信号）が往復しないこと。"""
    app, _ = color_app
    app._handle_command("set_roi", make_frame(), x=0.2, y=0.3, w=0.6, h=0.5)

    class FixedScore:
        strategy_name = "color_mask"
        threshold = 0.1

        def __init__(self):
            self.scores = iter([0.12] * 6 + [0.09, 0.11, 0.08, 0.10, 0.09, 0.11, 0.08] * 6)

        def detect(self, frame):
            from capper_monitor.detection.base import DetectionResult

            s = next(self.scores)
            return DetectionResult(line_visible=s >= 0.1, score=s, debug_frame=None)

    app.detector = FixedScore()
    outputs = []
    for _ in range(6 + 7 * 6):
        app._process_frame(make_frame())
        outputs.append(app.gpio.alarm_output.is_on)
    assert outputs[-30:] == [True] * 30
    status = app.frame_buffer.get_status()
    assert status["score_min_60s"] == 0.08 and status["score_max_60s"] == 0.12
    assert abs(status["release_threshold"] - 0.06) < 1e-9
