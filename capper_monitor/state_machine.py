from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AlarmState(Enum):
    NORMAL = "normal"
    STEADY = "steady"
    BLINK = "blink"


class DetectionDebouncer:
    """ON遅延／OFF遅延によるヒステリシス。raw値のチャタリングを吸収する。"""

    def __init__(self, on_delay_s: float, off_delay_s: float):
        self._on_delay_s = on_delay_s
        self._off_delay_s = off_delay_s
        self._stable_value = False
        self._pending_value: Optional[bool] = None
        self._pending_since: Optional[float] = None

    def update(self, raw_value: bool, now: float) -> bool:
        if raw_value == self._stable_value:
            self._pending_value = None
            self._pending_since = None
            return self._stable_value

        if self._pending_value != raw_value:
            self._pending_value = raw_value
            self._pending_since = now

        delay = self._on_delay_s if raw_value else self._off_delay_s
        if now - self._pending_since >= delay:
            self._stable_value = raw_value
            self._pending_value = None
            self._pending_since = None

        return self._stable_value


@dataclass
class StateMachineResult:
    state: AlarmState
    output_on: bool
    transitioned: bool
    reason: str


class AlarmStateMachine:
    """ライン検知(デバウンス後)＋モーション検知＋リセットから最終的な出力状態を決定する。

    非ラッチ方式: reset_requested は即座に NORMAL へ強制する上書き操作であり、
    ラインが実際に見え続けている場合は次の検知サイクルで再度 STEADY/BLINK に戻る
    （デバウンサ自体の内部タイマーはリセットしないため）。
    """

    def __init__(self, debouncer: DetectionDebouncer, blink_interval_s: float):
        self._debouncer = debouncer
        self._blink_interval_s = blink_interval_s
        self._state = AlarmState.NORMAL
        self._blink_phase_start: Optional[float] = None

    @property
    def state(self) -> AlarmState:
        return self._state

    def update(
        self,
        raw_line_visible: bool,
        motion_detected: bool,
        reset_requested: bool,
        now: float,
    ) -> StateMachineResult:
        debounced = self._debouncer.update(raw_line_visible, now)
        prev_state = self._state

        if reset_requested:
            new_state = AlarmState.NORMAL
            reason = "reset"
        elif not debounced:
            new_state = AlarmState.NORMAL
            reason = "line_cleared" if prev_state != AlarmState.NORMAL else "no_change"
        elif motion_detected:
            new_state = AlarmState.BLINK
            reason = "refill_in_progress" if prev_state != AlarmState.BLINK else "no_change"
        else:
            new_state = AlarmState.STEADY
            reason = "line_detected" if prev_state != AlarmState.STEADY else "no_change"

        transitioned = new_state != prev_state
        self._state = new_state

        if new_state == AlarmState.NORMAL:
            output_on = False
            self._blink_phase_start = None
        elif new_state == AlarmState.STEADY:
            output_on = True
            self._blink_phase_start = None
        else:
            if transitioned or self._blink_phase_start is None:
                self._blink_phase_start = now
            elapsed = now - self._blink_phase_start
            phases_passed = int(elapsed // self._blink_interval_s)
            output_on = phases_passed % 2 == 0

        return StateMachineResult(
            state=new_state,
            output_on=output_on,
            transitioned=transitioned,
            reason=reason,
        )
