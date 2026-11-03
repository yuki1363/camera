import pytest

from capper_monitor.camera import picamera2_backend  # noqa: F401  (importできることを確認)
from capper_monitor.camera.factory import create_camera
from capper_monitor.camera.opencv_backend import OpenCvBackend
from capper_monitor.camera.picamera2_backend import Picamera2Backend
from capper_monitor.config import CameraConfig


def test_import_picamera2_backend_module_does_not_require_picamera2_package():
    # このテスト自体が「importに成功すること」を検証している（本コンテナにpicamera2は未インストール）。
    assert picamera2_backend.Picamera2Backend is not None


def test_create_camera_opencv():
    cfg = CameraConfig(backend="opencv")
    cam = create_camera(cfg)
    assert isinstance(cam, OpenCvBackend)


def test_create_camera_picamera2():
    cfg = CameraConfig(backend="picamera2")
    cam = create_camera(cfg)
    assert isinstance(cam, Picamera2Backend)


def test_picamera2_open_without_package_raises_clear_error():
    cfg = CameraConfig(backend="picamera2")
    cam = create_camera(cfg)
    with pytest.raises(RuntimeError, match="picamera2"):
        cam.open()
