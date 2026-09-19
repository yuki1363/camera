from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from .base import DetectionResult, DetectionStrategy
from .roi import RoiFractional


def _extract_dilated_edges(
    bgr_img: np.ndarray,
    blur_kernel: int,
    canny_low: int,
    canny_high: int,
    dilate_kernel: int,
) -> np.ndarray:
    gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (blur_kernel, blur_kernel), 0)
    edges = cv2.Canny(blurred, canny_low, canny_high)
    kernel = np.ones((dilate_kernel, dilate_kernel), np.uint8)
    return cv2.dilate(edges, kernel)


class BaselineDiffDetector(DetectionStrategy):
    """複数枚の中央値画像から作った基準エッジマップとの差分方式（既定・主方式）。

    照明変化・背景の固定模様による誤検知を抑えるため、基準エッジをdilateしてから
    差分を取り、稼働中の微振動・数ピクセルの画角ズレを吸収する。
    """

    def __init__(
        self,
        roi: RoiFractional,
        dilate_kernel: int,
        canny_low: int,
        canny_high: int,
        blur_kernel: int,
        density_threshold: float,
        reference_edges: Optional[np.ndarray] = None,
    ):
        self._roi = roi
        self._dilate_kernel = dilate_kernel
        self._canny_low = canny_low
        self._canny_high = canny_high
        self._blur_kernel = blur_kernel
        self._density_threshold = density_threshold
        self._reference_edges = reference_edges

    @property
    def is_ready(self) -> bool:
        return self._reference_edges is not None

    def set_reference(self, reference_edges: np.ndarray) -> None:
        self._reference_edges = reference_edges

    def detect(self, frame: np.ndarray) -> DetectionResult:
        if self._reference_edges is None:
            raise RuntimeError(
                "BaselineDiffDetector: 基準画像が未設定です。scripts/calibrate.py で"
                "基準フレームを取得してください。"
            )
        roi_img = self._roi.crop(frame)
        current_edges = _extract_dilated_edges(
            roi_img, self._blur_kernel, self._canny_low, self._canny_high, self._dilate_kernel
        )
        if current_edges.shape != self._reference_edges.shape:
            raise RuntimeError(
                "BaselineDiffDetector: 現在フレームのROIサイズが基準画像と一致しません"
                f"（現在={current_edges.shape}, 基準={self._reference_edges.shape}）。"
                "カメラ解像度やROI設定が基準取得時と変わっていないか確認してください。"
            )
        new_edges = cv2.bitwise_and(current_edges, cv2.bitwise_not(self._reference_edges))
        density = float(np.count_nonzero(new_edges)) / new_edges.size if new_edges.size else 0.0
        return DetectionResult(
            line_visible=density >= self._density_threshold,
            score=density,
            debug_frame=new_edges,
        )

    def build_reference_from_frames(self, frames: List[np.ndarray]) -> np.ndarray:
        if not frames:
            raise ValueError("基準フレームが1枚もありません")
        crops = [self._roi.crop(f).astype(np.float32) for f in frames]
        median_img = np.median(np.stack(crops, axis=0), axis=0).astype(np.uint8)
        reference_edges = _extract_dilated_edges(
            median_img, self._blur_kernel, self._canny_low, self._canny_high, self._dilate_kernel
        )
        self._reference_edges = reference_edges
        return reference_edges

    def save_reference(self, path: str | Path) -> None:
        if self._reference_edges is None:
            raise RuntimeError("保存する基準画像がありません")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, self._reference_edges)

    @staticmethod
    def load_reference(path: str | Path) -> Optional[np.ndarray]:
        path = Path(path)
        if not path.is_file():
            return None
        return np.load(path)
