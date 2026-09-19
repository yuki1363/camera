from __future__ import annotations

import cv2
import numpy as np

from capper_monitor.detection.roi import RoiFractional


def make_frame(width: int = 200, height: int = 200, color=(200, 200, 200)) -> np.ndarray:
    return np.full((height, width, 3), color, dtype=np.uint8)


def add_noise(frame: np.ndarray, sigma: float = 5.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, sigma, frame.shape)
    noisy = frame.astype(np.float32) + noise
    return np.clip(noisy, 0, 255).astype(np.uint8)


def shift_brightness(frame: np.ndarray, delta: int) -> np.ndarray:
    shifted = frame.astype(np.int16) + delta
    return np.clip(shifted, 0, 255).astype(np.uint8)


def draw_line_in_roi(frame: np.ndarray, roi: RoiFractional, thickness: int = 3, color=(0, 0, 0)) -> np.ndarray:
    x0, y0, x1, y1 = roi.to_pixels(frame.shape)
    cy = (y0 + y1) // 2
    cv2.line(frame, (x0, cy), (x1, cy), color, thickness)
    return frame


def draw_fixed_clutter(frame: np.ndarray, center=(20, 20), radius: int = 4, color=(0, 0, 0)) -> np.ndarray:
    cv2.circle(frame, center, radius, color, -1)
    return frame
