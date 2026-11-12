from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

from capper_monitor.config import OpenCvCameraConfig

from .base import CameraBackend

logger = logging.getLogger(__name__)


class OpenCvBackend(CameraBackend):
    """USBウェブカメラ等をcv2.VideoCaptureで取得するバックエンド。"""

    def __init__(self, config: OpenCvCameraConfig):
        self._config = config
        self._cap: Optional[cv2.VideoCapture] = None

    def open(self) -> None:
        cap = cv2.VideoCapture(self._config.device_index)
        if not cap.isOpened():
            raise RuntimeError(f"カメラを開けません (device_index={self._config.device_index})")
        # 形式(MJPG等)は解像度より先に指定する。後から指定すると、多くのUSBカメラで
        # 解像度が既定(640x480)へ戻る、または高解像度を選べないまま動く
        if self._config.fourcc:
            fourcc = cv2.VideoWriter_fourcc(*self._config.fourcc)
            cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._config.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._config.height)
        actual = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        if actual != (self._config.width, self._config.height):
            logger.warning(
                "カメラが指定の解像度になりませんでした（指定 %dx%d、実際 %dx%d）",
                self._config.width,
                self._config.height,
                *actual,
            )
        self._cap = cap

    def read(self) -> Optional[np.ndarray]:
        if self._cap is None:
            return None
        try:
            ok, frame = self._cap.read()
        except cv2.error:
            logger.exception("OpenCvBackend: フレーム読取中に例外が発生しました")
            return None
        if not ok or frame is None:
            return None
        return frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
