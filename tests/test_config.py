from pathlib import Path

import pytest

from capper_monitor.config import ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"


def test_load_default_config_succeeds():
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.camera.backend == "opencv"
    assert config.detection.strategy == "baseline_diff"
    assert config.gpio.pin_factory == "lgpio"


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
