from __future__ import annotations

import logging

from capper_monitor.config import DetectionConfig

from .alignment_check import AlignmentChecker
from .base import DetectionStrategy
from .baseline_diff import BaselineDiffDetector
from .color_mask import ColorMaskDetector
from .edge_density import EdgeDensityDetector
from .motion import MotionDetector
from .roi import RoiFractional

logger = logging.getLogger(__name__)


def _roi(cfg) -> RoiFractional:
    return RoiFractional(x=cfg.x, y=cfg.y, w=cfg.w, h=cfg.h)


def create_strategy(name: str, cfg: DetectionConfig, load_reference: bool = True) -> DetectionStrategy:
    roi = _roi(cfg.roi)
    if name == "edge_density":
        c = cfg.edge_density
        return EdgeDensityDetector(
            roi=roi,
            canny_low=c.canny_low,
            canny_high=c.canny_high,
            blur_kernel=c.blur_kernel,
            density_threshold=c.density_threshold,
            adaptive=c.adaptive,
        )
    if name == "color_mask":
        c = cfg.color_mask
        return ColorMaskDetector(
            roi=roi,
            hsv_lower=c.hsv_lower,
            hsv_upper=c.hsv_upper,
            pixel_ratio_threshold=c.pixel_ratio_threshold,
        )
    if name == "baseline_diff":
        c = cfg.baseline_diff
        reference = BaselineDiffDetector.load_reference(c.reference_path) if load_reference else None
        return BaselineDiffDetector(
            roi=roi,
            dilate_kernel=c.dilate_kernel,
            canny_low=c.canny_low,
            canny_high=c.canny_high,
            blur_kernel=c.blur_kernel,
            density_threshold=c.density_threshold,
            reference_edges=reference,
        )
    raise ValueError(f"未知の検知方式です: {name!r}")


def create_detector(cfg: DetectionConfig, load_reference: bool = True) -> DetectionStrategy:
    """主方式を生成する。baseline_diffで基準画像が未取得の場合はfallback_strategyを返す。

    load_reference=False はROI変更直後など、保存済みの基準画像が新しいROIと
    合わなくなった場合に使う。
    """
    primary = create_strategy(cfg.strategy, cfg, load_reference)
    if primary.is_ready:
        return primary
    logger.warning(
        "detection_strategy_fallback configured=%s fallback=%s (基準画像未取得のためフォールバック)",
        cfg.strategy,
        cfg.fallback_strategy,
    )
    return create_strategy(cfg.fallback_strategy, cfg, load_reference)


def create_alignment_checker(cfg: DetectionConfig) -> AlignmentChecker:
    c = cfg.alignment_check
    reference = AlignmentChecker.load_reference(c.reference_path)
    return AlignmentChecker(roi=_roi(c.roi), correlation_threshold=c.correlation_threshold, reference_gray=reference)


def create_motion_detector(cfg: DetectionConfig) -> MotionDetector:
    c = cfg.refill_detection
    return MotionDetector(motion_threshold=c.motion_threshold, motion_ratio=c.motion_ratio)
