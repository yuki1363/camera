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

    @property
    def hsv_range(self):
        return tuple(int(v) for v in self._hsv_lower), tuple(int(v) for v in self._hsv_upper)

    def set_hsv_range(self, hsv_lower, hsv_upper) -> None:
        self._hsv_lower = np.array(hsv_lower, dtype=np.uint8)
        self._hsv_upper = np.array(hsv_upper, dtype=np.uint8)

    def mask_of(self, bgr: np.ndarray) -> np.ndarray:
        """画像のうち、設定した色の範囲に入る画素を255にしたマスクを返す（画面表示用）。"""
        return self._mask(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV))

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


# 見本の色から範囲を作るときの余裕（色相・彩度・明度）。照明の揺れ・影を吸収する
_HUE_MARGIN = 6
_SV_LOWER_SCALE = 0.75


def learn_hsv_range(sample_bgr: np.ndarray):
    """見本（テープの上の画像）から、その色だけを拾うHSV範囲 (lower, upper) を作る。

    色相は0/180をまたぐ色（赤）でも扱えるよう、90ずらして集計する。
    下限は見本の下位5%に余裕を持たせ、上限は 255 にする（明るい側は広く許す）。
    """
    hsv = cv2.cvtColor(sample_bgr, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    if len(hsv) == 0:
        raise ValueError("見本の画素がありません")
    # 暗すぎる・色が薄すぎる画素は、テープ以外（影・ハイライト）なので見本から外す
    colored = hsv[(hsv[:, 1] >= 40) & (hsv[:, 2] >= 40)]
    if len(colored) < max(20, len(hsv) // 10):
        raise ValueError("見本に色のついた部分が少なすぎます。テープの上だけを囲んでください")
    shifted = (colored[:, 0].astype(int) + 90) % 180
    h_lo = int(np.percentile(shifted, 5)) - _HUE_MARGIN
    h_hi = int(np.percentile(shifted, 95)) + _HUE_MARGIN
    if h_hi - h_lo > 40:
        raise ValueError("見本の色がばらばらです。テープの上だけを囲んでください")
    lower_h = (h_lo - 90) % 180
    upper_h = (h_hi - 90) % 180
    s_lo = max(40, int(np.percentile(colored[:, 1], 5) * _SV_LOWER_SCALE))
    v_lo = max(40, int(np.percentile(colored[:, 2], 5) * _SV_LOWER_SCALE))
    return (lower_h, s_lo, v_lo), (upper_h, 255, 255)
