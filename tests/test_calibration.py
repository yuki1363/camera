import shutil
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

import pytest

from capper_monitor.calibration import CalibrationError, CommandQueue, save_calibration, with_threshold
from capper_monitor.config import DetectionConfig, RoiConfig, load_config

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config" / "config.yaml"


def test_submit_returns_handler_result_from_other_thread():
    commands = CommandQueue()
    results = {}

    def submitter():
        results["value"] = commands.submit("set_threshold", value=0.1)

    thread = threading.Thread(target=submitter)
    thread.start()
    calls = []
    while thread.is_alive():
        commands.drain(lambda name, **kwargs: calls.append((name, kwargs)) or {"message": "ok"})
        thread.join(timeout=0.01)

    assert results["value"] == {"message": "ok"}
    assert calls == [("set_threshold", {"value": 0.1})]


def test_handler_error_is_raised_to_submitter():
    commands = CommandQueue()
    errors = []

    def submitter():
        try:
            commands.submit("save")
        except CalibrationError as exc:
            errors.append(str(exc))

    def handler(name, **kwargs):
        raise CalibrationError("基準フレームが未撮影です")

    thread = threading.Thread(target=submitter)
    thread.start()
    while thread.is_alive():
        commands.drain(handler)
        thread.join(timeout=0.01)

    assert errors == ["基準フレームが未撮影です"]


def test_timed_out_command_is_not_executed_later():
    commands = CommandQueue()
    with pytest.raises(FutureTimeoutError):
        commands.submit("capture_baseline", timeout=0.05)

    calls = []
    commands.drain(lambda name, **kwargs: calls.append(name) or {})
    assert calls == []


def test_with_threshold_updates_the_right_field():
    cfg = DetectionConfig()
    assert with_threshold(cfg, "baseline_diff", 0.2).baseline_diff.density_threshold == 0.2
    assert with_threshold(cfg, "edge_density", 0.3).edge_density.density_threshold == 0.3
    assert with_threshold(cfg, "color_mask", 0.4).color_mask.pixel_ratio_threshold == 0.4
    with pytest.raises(CalibrationError):
        with_threshold(cfg, "unknown", 0.1)


def test_save_calibration_updates_values_and_keeps_comments(tmp_path):
    path = tmp_path / "config.yaml"
    shutil.copy(REPO_CONFIG, path)

    save_calibration(
        path,
        roi=RoiConfig(x=0.1, y=0.2, w=0.3, h=0.25),
        thresholds={"baseline_diff": 0.033, "edge_density": 0.07, "color_mask": 0.15},
    )

    config = load_config(path)
    assert config.detection.roi == RoiConfig(x=0.1, y=0.2, w=0.3, h=0.25)
    assert config.detection.baseline_diff.density_threshold == 0.033
    assert config.detection.edge_density.density_threshold == 0.07
    assert config.detection.color_mask.pixel_ratio_threshold == 0.15
    # 他の設定値とコメントが残っていること
    assert config.camera.backend == "opencv"
    assert "基準との差分エッジ密度がこの比率を超えたら" in path.read_text(encoding="utf-8")


def test_save_calibration_persists_motion_settings_and_keeps_comments(tmp_path):
    path = tmp_path / "config.yaml"
    shutil.copy(REPO_CONFIG, path)

    save_calibration(path, motion_roi=RoiConfig(x=0.2, y=0.3, w=0.4, h=0.5), motion_ratio=0.031)

    refill = load_config(path).detection.refill_detection
    assert refill.roi == RoiConfig(x=0.2, y=0.3, w=0.4, h=0.5)
    assert refill.motion_ratio == 0.031
    assert refill.blink_interval_ms == 400  # 他の設定は変わらない
    assert "キャップ投入中の点滅周期" in path.read_text(encoding="utf-8")
