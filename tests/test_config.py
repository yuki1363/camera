from pathlib import Path

import pytest

from capper_monitor.config import ConfigError, GpioConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"


def test_load_default_config_succeeds():
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.camera.backend == "opencv"
    assert config.detection.strategy == "color_mask"
    assert config.gpio.pin_factory == "lgpio"


def test_default_config_uses_red_hue_wraparound_preset():
    cm = load_config(DEFAULT_CONFIG_PATH).detection.color_mask
    assert cm.hsv_lower[0] > cm.hsv_upper[0]  # 赤は色相0/180をまたぐ
    assert cm.hsv_lower[1] >= 50  # 白（低彩度）を除外できる彩度下限


@pytest.mark.parametrize(
    "lower,upper",
    [
        ([181, 80, 60], [10, 255, 255]),   # 色相は0〜180
        ([170, 80, 60], [10, 256, 255]),   # 彩度は0〜255
        ([170, -1, 60], [10, 255, 255]),
        ([170, 200, 60], [10, 100, 255]),  # 彩度 lower > upper
    ],
)
def test_color_mask_out_of_range_hsv_raises(tmp_path, lower, upper):
    path = tmp_path / "config.yaml"
    path.write_text(
        f"detection:\n  color_mask:\n    hsv_lower: {lower}\n    hsv_upper: {upper}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does_not_exist.yaml")


def test_invalid_backend_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("camera:\n  backend: not_a_backend\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_invalid_strategy_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("detection:\n  strategy: not_a_strategy\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_roi_out_of_range_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "detection:\n  roi:\n    x: 0.9\n    y: 0.1\n    w: 0.5\n    h: 0.1\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_even_blur_kernel_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "detection:\n  edge_density:\n    blur_kernel: 4\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_duplicate_gpio_pin_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "gpio:\n"
        "  alarm_output:\n"
        "    pin: 17\n"
        "  reset_button:\n"
        "    pin: 17\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_malformed_yaml_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("camera: [this is not: valid\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_baseline_diff_invalid_canny_range_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "detection:\n  baseline_diff:\n    canny_low: 150\n    canny_high: 50\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_invalid_autofocus_mode_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "camera:\n  backend: picamera2\n  picamera2:\n    autofocus_mode: not_a_mode\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_manual_autofocus_without_lens_position_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "camera:\n  backend: picamera2\n  picamera2:\n    autofocus_mode: manual\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_manual_autofocus_with_lens_position_succeeds(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "camera:\n"
        "  backend: picamera2\n"
        "  picamera2:\n"
        "    autofocus_mode: manual\n"
        "    lens_position: 4.5\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.camera.picamera2.autofocus_mode == "manual"
    assert config.camera.picamera2.lens_position == 4.5


def test_default_autofocus_mode_is_auto():
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.camera.picamera2.autofocus_mode == "auto"


def test_default_ae_awb_convergence_s_is_positive():
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.camera.picamera2.ae_awb_convergence_s > 0


def test_non_positive_ae_awb_convergence_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "camera:\n  backend: picamera2\n  picamera2:\n    ae_awb_convergence_s: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_invalid_awb_mode_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "camera:\n  backend: picamera2\n  picamera2:\n    awb_mode: not_a_mode\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_daylight_awb_mode_succeeds(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "camera:\n  backend: picamera2\n  picamera2:\n    awb_mode: daylight\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.camera.picamera2.awb_mode == "daylight"


def test_default_awb_mode_is_auto():
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.camera.picamera2.awb_mode == "auto"


def test_negative_camera_dimensions_raise(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("camera:\n  opencv:\n    width: 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_negative_web_stream_dimensions_raise(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("web:\n  stream_width: -1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_reset_button_default_bounce_time_matches_yaml_default(tmp_path):
    # dataclassを直接構築した場合とYAML読み込み(値未指定)の場合とでデフォルト値が
    # 食い違わないことを確認する回帰テスト。
    path = tmp_path / "config.yaml"
    path.write_text("gpio:\n  reset_button:\n    pin: 27\n", encoding="utf-8")
    loaded = load_config(path)
    assert loaded.gpio.reset_button.bounce_time_ms == GpioConfig().reset_button.bounce_time_ms


def test_reference_path_resolved_relative_to_config_file_not_cwd(tmp_path, monkeypatch):
    subdir = tmp_path / "site_a"
    subdir.mkdir()
    path = subdir / "config.yaml"
    path.write_text(
        "detection:\n"
        "  baseline_diff:\n"
        "    reference_path: baseline_reference.npy\n",
        encoding="utf-8",
    )
    other_cwd = tmp_path / "somewhere_else"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    config = load_config(path)
    assert config.detection.baseline_diff.reference_path == str(subdir / "baseline_reference.npy")


def test_gpio_chip_defaults_to_auto():
    assert load_config(DEFAULT_CONFIG_PATH).gpio.chip == "auto"


def test_gpio_chip_accepts_explicit_number(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("gpio:\n  chip: 13\n", encoding="utf-8")
    assert load_config(path).gpio.chip == 13


@pytest.mark.parametrize("value", ["-1", "rp1", "true"])
def test_gpio_chip_invalid_value_raises(tmp_path, value):
    path = tmp_path / "config.yaml"
    path.write_text(f"gpio:\n  chip: {value}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_refill_roi_defaults_to_none_meaning_whole_frame():
    assert load_config(DEFAULT_CONFIG_PATH).detection.refill_detection.roi is None


def test_refill_roi_is_loaded(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "detection:\n  refill_detection:\n    roi:\n      x: 0.1\n      y: 0.2\n      w: 0.3\n      h: 0.4\n",
        encoding="utf-8",
    )
    roi = load_config(path).detection.refill_detection.roi
    assert (roi.x, roi.y, roi.w, roi.h) == (0.1, 0.2, 0.3, 0.4)


def test_refill_roi_out_of_range_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "detection:\n  refill_detection:\n    roi:\n      x: 0.8\n      y: 0.2\n      w: 0.5\n      h: 0.4\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_shutdown_is_off_by_default_in_code_but_on_in_template(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("web:\n  enabled: true\n", encoding="utf-8")
    assert load_config(path).web.shutdown_enabled is False
    assert load_config(DEFAULT_CONFIG_PATH).web.shutdown_enabled is True
