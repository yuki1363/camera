from __future__ import annotations

import cv2
import numpy as np

from .base import DetectionResult, DetectionStrategy
from .roi import RoiFractional


class ColorMaskDetector(DetectionStrategy):
    """HSV色マスク方式。ラインの色が既知の場合の代替方式（既定では無効化推奨）。"""

    def __init__(
        self,
        roi: RoiFractional,
        hsv_lower,
        hsv_upper,
        pixel_ratio_threshold: float,
    ):
        self._roi = roi
        self._hsv_lower = np.array(hsv_lower, dtype=np.uint8)
        self._hsv_upper = np.array(hsv_upper, dtype=np.uint8)
        self._pixel_ratio_threshold = pixel_ratio_threshold

    def detect(self, frame: np.ndarray) -> DetectionResult:
        roi_img = self._roi.crop(frame)
        hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self._hsv_lower, self._hsv_upper)
        ratio = float(np.count_nonzero(mask)) / mask.size if mask.size else 0.0
        return DetectionResult(
            line_visible=ratio >= self._pixel_ratio_threshold,
            score=ratio,
            debug_frame=mask,
        )
