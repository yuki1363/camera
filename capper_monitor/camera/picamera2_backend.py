from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

from capper_monitor.config import Picamera2CameraConfig

from .base import CameraBackend

logger = logging.getLogger(__name__)


def _import_picamera2():
    try:
        from picamera2 import Picamera2
    except ImportError as exc:
        raise RuntimeError(
            "picamera2 がインストールされていません。ラズパイ実機では"
            "`sudo apt install -y python3-picamera2` を実行し、"
            "venvを`--system-site-packages`付きで作成してください。"
        ) from exc
    return Picamera2


class Picamera2Backend(CameraBackend):
    """ラズパイ純正CSIカメラモジュール用バックエンド。

    picamera2はモジュールトップレベルではimportせず、open()内で遅延importする。
    これにより、picamera2が未インストールの環境（本開発コンテナや将来のUSBカメラ
    のみの現場）でもこのモジュール自体のimportやテストは失敗しない。
    """

    def __init__(self, config: Picamera2CameraConfig):
        self._config = config
        self._cam = None

    def open(self) -> None:
        Picamera2 = _import_picamera2()
        self._cam = Picamera2()
        video_config = self._cam.create_video_configuration(
            main={"size": (self._config.width, self._config.height), "format": "RGB888"}
        )
        self._cam.configure(video_config)
        if not self._config.auto_exposure:
            self._cam.set_controls({"AeEnable": False})
        if not self._config.auto_white_balance:
            self._cam.set_controls({"AwbEnable": False})
        self._cam.start()

    def read(self) -> Optional[np.ndarray]:
        if self._cam is None:
            return None
        try:
            rgb = self._cam.capture_array()
        except Exception:
            logger.exception("Picamera2Backend: フレーム読取中に例外が発生しました")
            return None
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def close(self) -> None:
        if self._cam is not None:
            self._cam.stop()
            self._cam = None
