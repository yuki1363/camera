from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class FilteredScore:
    score: float            # ならした値（直近の中央値）
    line_visible: bool
    release_threshold: float


class ScoreFilter:
    """1フレームごとのスコアの揺れを抑えて、ライン見える／見えないを決める。

    - 直近 window フレームのスコアの中央値で判定する（単発の外れ値を無視）
    - 2段しきい値（ヒステリシス）: しきい値以上で「見える」になり、
      しきい値 × release_ratio を下回るまで「見える」を保つ。しきい値付近で往復しない。
    しきい値は毎回渡す（スマホから変更された値をそのまま使うため）。
    """

    def __init__(self, window: int, release_ratio: float):
        self._scores: deque = deque(maxlen=max(1, window))
        self._release_ratio = release_ratio
        self._visible = False

    def update(self, score: float, threshold: float) -> FilteredScore:
        self._scores.append(score)
        smoothed = float(np.median(self._scores))
        release = threshold * self._release_ratio
        if self._visible:
            self._visible = smoothed >= release
        else:
            self._visible = smoothed >= threshold
        return FilteredScore(score=smoothed, line_visible=self._visible, release_threshold=release)

    def clear(self) -> None:
        self._scores.clear()
        self._visible = False
