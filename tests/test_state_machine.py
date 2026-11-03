from capper_monitor.state_machine import AlarmState, AlarmStateMachine, DetectionDebouncer


def make_machine(on_delay_s=0.5, off_delay_s=1.0, blink_interval_s=0.4):
    debouncer = DetectionDebouncer(on_delay_s=on_delay_s, off_delay_s=off_delay_s)
    return AlarmStateMachine(debouncer, blink_interval_s=blink_interval_s)


def test_debouncer_requires_sustained_on_delay():
    d = DetectionDebouncer(on_delay_s=0.5, off_delay_s=1.0)
    assert d.update(True, now=0.0) is False
    assert d.update(True, now=0.3) is False
    assert d.update(True, now=0.6) is True


def test_debouncer_flicker_resets_pending_timer():
    d = DetectionDebouncer(on_delay_s=0.5, off_delay_s=1.0)
    assert d.update(True, now=0.0) is False
    assert d.update(False, now=0.3) is False
    assert d.update(True, now=0.4) is False
    assert d.update(True, now=0.85) is False
    assert d.update(True, now=0.95) is True


def test_debouncer_requires_sustained_off_delay():
    d = DetectionDebouncer(on_delay_s=0.5, off_delay_s=1.0)
    d.update(True, now=0.0)
    assert d.update(True, now=0.6) is True
    assert d.update(False, now=0.8) is True
    assert d.update(False, now=1.7) is True
    assert d.update(False, now=1.9) is False


def test_line_detected_transitions_to_steady_after_on_delay():
    m = make_machine()
    r = m.update(raw_line_visible=True, motion_detected=False, reset_requested=False, now=0.0)
    assert r.state == AlarmState.NORMAL
    assert r.output_on is False

    r = m.update(raw_line_visible=True, motion_detected=False, reset_requested=False, now=0.6)
    assert r.state == AlarmState.STEADY
    assert r.output_on is True
    assert r.transitioned is True
    assert r.reason == "line_detected"


def test_line_cleared_returns_to_normal_after_off_delay():
    m = make_machine()
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    assert m.state == AlarmState.STEADY

    r = m.update(False, False, False, now=0.7)
    assert r.state == AlarmState.STEADY

    r = m.update(False, False, False, now=1.8)
    assert r.state == AlarmState.NORMAL
    assert r.output_on is False
    assert r.reason == "line_cleared"


def test_motion_detected_switches_to_blink_while_line_visible():
    m = make_machine()
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    assert m.state == AlarmState.STEADY

    r = m.update(True, True, False, now=0.7)
    assert r.state == AlarmState.BLINK
    assert r.reason == "refill_in_progress"


def test_reset_forces_normal_immediately_even_before_off_delay():
    m = make_machine()
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    assert m.state == AlarmState.STEADY

    r = m.update(True, False, reset_requested=True, now=0.61)
    assert r.state == AlarmState.NORMAL
    assert r.output_on is False
    assert r.reason == "reset"


def test_reset_does_not_prevent_reassertion_if_line_still_visible():
    m = make_machine()
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    assert m.state == AlarmState.STEADY

    m.update(True, False, reset_requested=True, now=0.61)
    assert m.state == AlarmState.NORMAL

    r = m.update(True, False, reset_requested=False, now=0.62)
    assert r.state == AlarmState.STEADY
    assert r.output_on is True


def test_blink_toggles_output_over_time():
    m = make_machine(blink_interval_s=0.4)
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    r = m.update(True, True, False, now=0.7)
    assert r.state == AlarmState.BLINK
    assert r.output_on is True

    r = m.update(True, True, False, now=0.7 + 0.5)
    assert r.output_on is False

    r = m.update(True, True, False, now=0.7 + 0.9)
    assert r.output_on is True


def test_startup_state_is_normal_with_output_off():
    m = make_machine()
    r = m.update(False, False, False, now=0.0)
    assert r.state == AlarmState.NORMAL
    assert r.output_on is False
    assert r.transitioned is False
    assert r.reason == "no_change"


def test_blink_to_steady_reason_is_refill_finished():
    m = make_machine()
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    m.update(True, True, False, now=0.7)
    assert m.state == AlarmState.BLINK

    r = m.update(True, False, False, now=0.8)
    assert r.state == AlarmState.STEADY
    assert r.reason == "refill_finished"


def test_force_normal_immediately_sets_normal_without_touching_debouncer():
    m = make_machine()
    m.update(True, False, False, now=0.0)
    m.update(True, False, False, now=0.6)
    assert m.state == AlarmState.STEADY

    r = m.force_normal(reason="reset")
    assert r.state == AlarmState.NORMAL
    assert r.output_on is False
    assert r.transitioned is True
    assert r.reason == "reset"

    # デバウンサの内部タイマーは維持されているため、rawがTrueのままなら
    # 次のupdate呼び出しで即座にSTEADYへ戻る（on_delayを待たない）。
    r = m.update(True, False, False, now=0.61)
    assert r.state == AlarmState.STEADY


def test_force_normal_is_no_op_transition_when_already_normal():
    m = make_machine()
    r = m.force_normal(reason="reset")
    assert r.transitioned is False
    assert r.state == AlarmState.NORMAL


# --- 補充中（動き）の判定を安定させるヒステリシス ---

def make_motion_machine(hold_s=3.0, enter_s=0.5):
    debouncer = DetectionDebouncer(on_delay_s=0.0, off_delay_s=0.0)
    return AlarmStateMachine(debouncer, blink_interval_s=0.4, motion_hold_s=hold_s, motion_enter_s=enter_s)


def step(machine, t, motion, line=True, reset=False):
    return machine.update(raw_line_visible=line, motion_detected=motion, reset_requested=reset, now=t)


def test_brief_motion_does_not_start_blinking():
    m = make_motion_machine()
    assert step(m, 0.0, False).state == AlarmState.STEADY
    assert step(m, 0.1, True).state == AlarmState.STEADY
    assert step(m, 0.2, True).state == AlarmState.STEADY
    assert step(m, 0.3, False).state == AlarmState.STEADY
    # 途切れたので、また最初から数え直す
    assert step(m, 0.4, True).state == AlarmState.STEADY
    assert step(m, 0.8, True).state == AlarmState.STEADY


def test_sustained_motion_starts_blinking():
    m = make_motion_machine()
    step(m, 0.0, True)
    assert step(m, 0.3, True).state == AlarmState.STEADY
    assert step(m, 0.6, True).state == AlarmState.BLINK


def test_flickering_motion_does_not_alternate_between_blink_and_steady():
    m = make_motion_machine()
    t = 0.0
    states = []
    for i in range(60):  # 0.1秒ごとに動きあり/なしが交互に入れ替わる
        states.append(step(m, t, i % 2 == 0).state)
        t += 0.1
    assert set(states) == {AlarmState.STEADY}


def test_blink_is_held_while_motion_flickers_off_and_returns_after_hold():
    m = make_motion_machine(hold_s=3.0, enter_s=0.5)
    step(m, 0.0, True)
    assert step(m, 0.6, True).state == AlarmState.BLINK
    assert step(m, 1.0, False).state == AlarmState.BLINK  # 途切れても保持
    assert step(m, 3.0, False).state == AlarmState.BLINK
    assert step(m, 3.7, False).state == AlarmState.STEADY  # 最後の動き(0.6)から3秒超


def test_motion_hold_is_extended_by_new_motion():
    m = make_motion_machine(hold_s=3.0, enter_s=0.5)
    step(m, 0.0, True)
    step(m, 0.6, True)
    step(m, 2.5, True)
    assert step(m, 5.0, False).state == AlarmState.BLINK
    assert step(m, 5.6, False).state == AlarmState.STEADY


def test_reset_clears_motion_hold():
    m = make_motion_machine()
    step(m, 0.0, True)
    assert step(m, 0.6, True).state == AlarmState.BLINK
    assert step(m, 0.7, False, reset=True).state == AlarmState.NORMAL
    assert step(m, 0.8, False).state == AlarmState.STEADY  # 保持は残らない


def test_zero_hold_and_enter_keep_previous_behavior():
    m = make_motion_machine(hold_s=0.0, enter_s=0.0)
    assert step(m, 0.0, True).state == AlarmState.BLINK
    assert step(m, 0.1, False).state == AlarmState.STEADY
