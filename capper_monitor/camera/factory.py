from __future__ import annotations

from capper_monitor.config import CameraConfig

from .base import CameraBackend


def create_camera(config: CameraConfig) -> CameraBackend:
    if config.backend == "opencv":
        from .opencv_backend import OpenCvBackend

        return OpenCvBackend(config.opencv)
    if config.backend == "picamera2":
        from .picamera2_backend import Picamera2Backend

        return Picamera2Backend(config.picamera2)
    raise ValueError(f"未知のカメラバックエンドです: {config.backend!r}")
