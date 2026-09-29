from __future__ import annotations

import cv2
import numpy as np

from .base import DetectionResult, DetectionStrategy
from .roi import RoiFractional


class ColorMaskDetector(DetectionStrategy):
    """HSV色マスク方式。ROI内で指定色の画素が占める割合がしきい値以上ならライン検知。

    OpenCVのHSVは色相(H)が0〜180。赤は0と180の両端にまたがるため、
    hsv_lower の色相 > hsv_upper の色相のときは「一周をまたぐ範囲」とみなし、
    [lower_H〜180] と [0〜upper_H] の2範囲の和でマスクを作る
    （例: lower=[170,80,60], upper=[10,255,255] で赤全体）。
    """

    strategy_name = "color_mask"

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

    @property
    def threshold(self) -> float:
        return self._pixel_ratio_threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self._pixel_ratio_threshold = value

    def _mask(self, hsv: np.ndarray) -> np.ndarray:
        lower, upper = self._hsv_lower, self._hsv_upper
        if lower[0] <= upper[0]:
            return cv2.inRange(hsv, lower, upper)
        high_part = cv2.inRange(hsv, lower, np.array([180, upper[1], upper[2]], dtype=np.uint8))
        low_part = cv2.inRange(hsv, np.array([0, lower[1], lower[2]], dtype=np.uint8), upper)
        return cv2.bitwise_or(high_part, low_part)

    def detect(self, frame: np.ndarray) -> DetectionResult:
        roi_img = self._roi.crop(frame)
        hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
        mask = self._mask(hsv)
        ratio = float(np.count_nonzero(mask)) / mask.size if mask.size else 0.0
        return DetectionResult(
            line_visible=ratio >= self._pixel_ratio_threshold,
            score=ratio,
            debug_frame=mask,
        )
