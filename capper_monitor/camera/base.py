from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np


class CameraBackend(ABC):
    @abstractmethod
    def open(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self) -> Optional[np.ndarray]:
        """BGR uint8フレームを返す。一時的な読取失敗時はNoneを返す（例外は投げない）。"""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> "CameraBackend":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
