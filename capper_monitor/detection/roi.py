from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass(frozen=True)
class RoiFractional:
    """フレームサイズに対する比率(0.0〜1.0)でROIを保持する。解像度変更に対応するため。"""

    x: float
    y: float
    w: float
    h: float

    def to_pixels(self, frame_shape: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
        height, width = frame_shape[0], frame_shape[1]
        x0 = int(round(self.x * width))
        y0 = int(round(self.y * height))
        x1 = max(x0 + 1, int(round((self.x + self.w) * width)))
        y1 = max(y0 + 1, int(round((self.y + self.h) * height)))
        x1 = min(x1, width)
        y1 = min(y1, height)
        return x0, y0, x1, y1

    def crop(self, frame: np.ndarray) -> np.ndarray:
        x0, y0, x1, y1 = self.to_pixels(frame.shape)
        return frame[y0:y1, x0:x1]
