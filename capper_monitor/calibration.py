from __future__ import annotations

import queue
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, Optional

from capper_monitor.config import DetectionConfig

_THRESHOLD_KEYS = {
    "edge_density": "density_threshold",
    "baseline_diff": "density_threshold",
    "color_mask": "pixel_ratio_threshold",
}


class CalibrationError(Exception):
    """調整操作が受け付けられない理由（画面にそのまま表示する想定のメッセージ）。"""


class CommandQueue:
    """Web配信スレッドから、カメラを持つメインループへ調整コマンドを渡す。

    カメラと検知器を触るのはメインループだけにするため、Web側は依頼を積んで
    結果を待つだけにする。
    """

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()

    def submit(self, name: str, timeout: float = 15.0, **kwargs) -> dict:
        future: Future = Future()
        self._queue.put((name, kwargs, future))
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            # タイムアウト後に遅れて実行され、画面に出ていない操作が反映されるのを防ぐ
            future.cancel()
            raise

    def drain(self, handler: Callable[..., dict]) -> None:
        while True:
            try:
                name, kwargs, future = self._queue.get_nowait()
            except queue.Empty:
                return
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(handler(name, **kwargs))
            except Exception as exc:
                future.set_exception(exc)


def with_threshold(cfg: DetectionConfig, strategy: str, value: float) -> DetectionConfig:
    if strategy == "edge_density":
        return replace(cfg, edge_density=replace(cfg.edge_density, density_threshold=value))
    if strategy == "baseline_diff":
        return replace(cfg, baseline_diff=replace(cfg.baseline_diff, density_threshold=value))
    if strategy == "color_mask":
        return replace(cfg, color_mask=replace(cfg.color_mask, pixel_ratio_threshold=value))
    raise CalibrationError(f"しきい値を変更できない検知方式です: {strategy!r}")


def save_calibration(
    config_path: str | Path,
    roi=None,
    thresholds: Optional[Dict[str, float]] = None,
) -> None:
    """ROIと各方式のしきい値だけを書き換える。コメントや他の設定値はそのまま残す。"""
    from ruamel.yaml import YAML

    path = Path(config_path)
    yaml = YAML()
    yaml.preserve_quotes = True
    data = yaml.load(path)

    detection = data.setdefault("detection", {})
    if roi is not None:
        roi_map = detection.setdefault("roi", {})
        for key in ("x", "y", "w", "h"):
            roi_map[key] = round(float(getattr(roi, key)), 4)
    for strategy, value in (thresholds or {}).items():
        section = detection.setdefault(strategy, {})
        section[_THRESHOLD_KEYS[strategy]] = round(float(value), 4)

    yaml.dump(data, path)
