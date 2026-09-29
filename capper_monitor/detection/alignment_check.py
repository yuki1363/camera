from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .roi import RoiFractional


@dataclass
class AlignmentCheckResult:
    ok: bool
    correlation: float


class AlignmentChecker:
    """常時静止しているはずの背景領域を基準画像と相関比較し、カメラの位置ズレ／異常を検知する。

    相関が閾値を大きく下回った場合は検知結果を信用せず、安全側（誤ってPLCへ信号を
    送らない）に倒すための補助チェック。
    """

    def __init__(self, roi: RoiFractional, correlation_threshold: float, reference_gray: Optional[np.ndarray] = None):
        self._roi = roi
        self._correlation_threshold = correlation_threshold
        self._reference_gray = reference_gray

    @property
    def is_ready(self) -> bool:
        return self._reference_gray is not None

    def build_reference_from_frame(self, frame: np.ndarray) -> np.ndarray:
        roi_img = self._roi.crop(frame)
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        self._reference_gray = gray
        return gray

    def check(self, frame: np.ndarray) -> AlignmentCheckResult:
        if self._reference_gray is None:
            return AlignmentCheckResult(ok=True, correlation=1.0)
        roi_img = self._roi.crop(frame)
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        if gray.shape != self._reference_gray.shape:
            return AlignmentCheckResult(ok=False, correlation=0.0)
        result = cv2.matchTemplate(gray, self._reference_gray, cv2.TM_CCOEFF_NORMED)
        correlation = float(result[0, 0])
        return AlignmentCheckResult(ok=correlation >= self._correlation_threshold, correlation=correlation)

    def save_reference(self, path: str | Path) -> None:
        if self._reference_gray is None:
            raise RuntimeError("保存する基準画像がありません")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, self._reference_gray)

    @staticmethod
    def load_reference(path: str | Path) -> Optional[np.ndarray]:
        path = Path(path)
        if not path.is_file():
            return None
        return np.load(path)
