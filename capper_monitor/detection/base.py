from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class DetectionResult:
    line_visible: bool
    score: float
    debug_frame: Optional[np.ndarray] = None


class DetectionStrategy(ABC):
    @abstractmethod
    def detect(self, frame: np.ndarray) -> DetectionResult:
        raise NotImplementedError

    @property
    def is_ready(self) -> bool:
        """基準画像等の事前準備が必要な方式で、まだ準備できていない場合はFalseを返す。"""
        return True
