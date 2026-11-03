from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .roi import RoiFractional

_SMOOTHING_WINDOW = 3
_SMOOTHING_MIN_COUNT = 2


@dataclass
class MotionResult:
    motion_detected: bool
    ratio: float


class MotionDetector:
    """フレーム間差分による「キャップ投入中（動きあり）」検知。

    追加センサーなしで既存カメラのみを使い、直近フレームとの画素変化量が
    しきい値を超える状態を検知する。単発フレームのノイズによるチャタリングを
    抑えるため、直近数フレームの多数決で最終判定を行う（内部実装の詳細でありconfig化しない）。
    """

    def __init__(self, motion_threshold: int, motion_ratio: float, roi: Optional[RoiFractional] = None):
        self._motion_threshold = motion_threshold
        self._motion_ratio = motion_ratio
        # None なら画面全体を見る
        self._roi = roi
        self._prev_gray: Optional[np.ndarray] = None
        self._history: deque = deque(maxlen=_SMOOTHING_WINDOW)

    @property
    def motion_ratio(self) -> float:
        return self._motion_ratio

    @motion_ratio.setter
    def motion_ratio(self, value: float) -> None:
        self._motion_ratio = value

    def detect(self, frame: np.ndarray) -> MotionResult:
        if self._roi is not None:
            frame = self._roi.crop(frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            self._prev_gray = gray
            self._history.append(False)
            return MotionResult(motion_detected=False, ratio=0.0)

        diff = cv2.absdiff(gray, self._prev_gray)
        self._prev_gray = gray
        changed = diff >= self._motion_threshold
        ratio = float(np.count_nonzero(changed)) / changed.size if changed.size else 0.0
        raw_motion = ratio >= self._motion_ratio
        self._history.append(raw_motion)

        smoothed = sum(self._history) >= _SMOOTHING_MIN_COUNT
        return MotionResult(motion_detected=smoothed, ratio=ratio)
