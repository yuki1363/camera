from __future__ import annotations

import cv2
import numpy as np

from .base import DetectionResult, DetectionStrategy
from .roi import RoiFractional

_AUTO_CANNY_SIGMA = 0.33


def _auto_canny_thresholds(gray: np.ndarray) -> tuple:
    median = float(np.median(gray))
    lower = int(max(0, (1.0 - _AUTO_CANNY_SIGMA) * median))
    upper = int(min(255, (1.0 + _AUTO_CANNY_SIGMA) * median))
    if upper <= lower:
        upper = lower + 1
    return lower, upper


class EdgeDensityDetector(DetectionStrategy):
    """Cannyエッジ密度の閾値方式。汎用的だが照明変化・背景の固定模様に弱いためフォールバック用。"""

    def __init__(
        self,
        roi: RoiFractional,
        canny_low: int,
        canny_high: int,
        blur_kernel: int,
        density_threshold: float,
        adaptive: bool = True,
    ):
        self._roi = roi
        self._canny_low = canny_low
        self._canny_high = canny_high
        self._blur_kernel = blur_kernel
        self._density_threshold = density_threshold
        self._adaptive = adaptive

    def detect(self, frame: np.ndarray) -> DetectionResult:
        roi_img = self._roi.crop(frame)
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (self._blur_kernel, self._blur_kernel), 0)

        if self._adaptive:
            low, high = _auto_canny_thresholds(blurred)
        else:
            low, high = self._canny_low, self._canny_high

        edges = cv2.Canny(blurred, low, high)
        density = float(np.count_nonzero(edges)) / edges.size if edges.size else 0.0
        return DetectionResult(
            line_visible=density >= self._density_threshold,
            score=density,
            debug_frame=edges,
        )
